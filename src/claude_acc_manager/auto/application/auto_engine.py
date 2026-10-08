"""auto_engine — the auto-switch engine: poll, decide, switch, record.

One ``tick()`` evaluates the fleet once: resolve the live account, run the
scheduled collection (active-when-due plus one stalest candidate, escalating
to everyone when the active nears the threshold band), classify the trigger,
rank candidates under the anti-flap gates, freshen the pick's parked
credential, then switch under the state lock and record the departure
snapshot the no-return guard needs next tick.

``tick`` never raises: port failures surface as ``ErrorEvent`` + ERROR so a
loop or cron wrapper keeps going. Loop-facing fields (``sleep_until_s``,
``blocked_long_wait``) are reset every tick and read by the delay policy.

Example:
    engine = AutoEngine(settings=..., ..., emit=events.append)
    outcome = engine.tick()  # TickOutcome.SWITCHED | NO_ACTION | BLOCKED | ERROR
"""

import datetime as dt
import math
import random
import threading
from collections.abc import Callable, Mapping

from claude_acc_manager.accounts.application.ports import (
    AccountDirPort,
    AccountStorePort,
    ActiveIdentityPort,
    LineageQuarantinePort,
    SwitchExecutorPort,
)
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.auto.application.ports import AutoStatePort, FreshenPort
from claude_acc_manager.auto.domain.auto_event import (
    AllExhaustedEvent,
    AutoEvent,
    ErrorEvent,
    NoSwitchEvent,
    PollEvent,
    QuarantinedEvent,
    SleepEvent,
    SwitchEvent,
    TickOutcome,
)
from claude_acc_manager.auto.domain.auto_state import AutoState
from claude_acc_manager.auto.domain.services import auto_rank, loop_delay
from claude_acc_manager.settings.domain.settings_spec import AutoSettings
from claude_acc_manager.usage.application.ports import (
    ClockPort,
    UsageCachePort,
    UsageFetchPort,
)
from claude_acc_manager.usage.domain.services import cache_trust, poll_policy
from claude_acc_manager.usage.domain.services.headroom import (
    account_headroom,
    relevant_windows,
)
from claude_acc_manager.usage.domain.usage_cache_entry import UsageCacheEntry
from claude_acc_manager.usage.domain.usage_report import UsageReport
from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot


class AutoEngine:
    """The auto-switch engine: one ``tick()`` per evaluation, never raises.

    Loop-facing attrs ``sleep_until_s`` / ``blocked_long_wait`` are reset at
    the top of every tick — the delay policy reads them after each call.
    """

    def __init__(
        self,
        *,
        settings: AutoSettings,
        active_identity: ActiveIdentityPort,
        store: AccountStorePort,
        account_files: AccountDirPort,
        usage_cache: UsageCachePort,
        fetch: UsageFetchPort,
        freshen: FreshenPort,
        quarantine: LineageQuarantinePort,
        switch_executor: SwitchExecutorPort,
        auto_state: AutoStatePort,
        clock: ClockPort,
        emit: Callable[[AutoEvent], None],
        dry_run: bool = False,
    ) -> None:
        """Store the injected settings, ports, and event sink."""
        self._settings = settings
        self._active_identity = active_identity
        self._store = store
        self._files = account_files
        self._cache = usage_cache
        self._fetch = fetch
        self._freshen = freshen
        self._quarantine = quarantine
        self._switch = switch_executor
        self._auto_state = auto_state
        self._clock = clock
        self._emit = emit
        self._dry_run = dry_run
        self.sleep_until_s: float | None = None
        self.blocked_long_wait = False
        self.next_poll_due_s: float | None = None
        self._stop = threading.Event()

    def tick(self) -> TickOutcome:
        """Evaluate once: poll usage, maybe switch. Never raises."""
        try:
            return self._tick_inner()
        except Exception as exc:  # safety net — every port failure is transient
            self._emit(ErrorEvent(message=f"{type(exc).__name__}: {exc}"))
            return TickOutcome.ERROR

    # -- loop ----------------------------------------------------------------

    def stop(self) -> None:
        """Ask ``run_loop`` to exit; wakes it from any sleep.

        Safe to call before the loop starts — the stop is never cleared, so
        the loop exits immediately (engines are single-use).
        """
        self._stop.set()

    def run_loop(self) -> int:
        """Tick forever (until ``stop``); a failing tick never kills it."""
        while True:
            if self._stop.is_set():
                return 0
            outcome = self.tick()
            delay = loop_delay.next_delay(
                outcome,
                interval_s=self._settings.interval_seconds,
                now_s=self._clock.now_epoch_s(),
                sleep_until_s=self.sleep_until_s,
                blocked_long_wait=self.blocked_long_wait,
                next_poll_due_s=self.next_poll_due_s,
                jitter=random.random(),
            )
            if delay > self._settings.interval_seconds * 1.5:
                self._emit(self._sleep_event(delay))
            self._stop.wait(delay)

    def _sleep_event(self, delay: float) -> SleepEvent:
        until = (
            dt.datetime.fromtimestamp(self._clock.now_epoch_s() + delay, tz=dt.UTC)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )
        return SleepEvent(seconds=delay, until=until)

    # -- pipeline -----------------------------------------------------------

    def _active_account(self) -> str | None:
        """The live slot's managed name; emits the refusal when it can't act."""
        identity = self._active_identity.execute()
        if identity is not None and identity.managed_as is not None:
            return identity.managed_as
        self._emit(
            PollEvent(
                active=None,
                headroom={},
                threshold=self._settings.threshold,
                fetch_errors={},
                windows={},
            )
        )
        if identity is None:
            self._emit(
                NoSwitchEvent(
                    reason="no-active-account",
                    detail="log in and run 'cam add' first",
                )
            )
        else:
            self._emit(
                NoSwitchEvent(
                    reason="unmanaged-active-account",
                    detail="run 'cam add' to include it in rotation",
                )
            )
        return None

    def _tick_inner(self) -> TickOutcome:
        self.sleep_until_s = None
        self.blocked_long_wait = False
        self.next_poll_due_s = None
        now = self._clock.now_epoch_s()
        state = self._auto_state.load()
        current = self._active_account()
        if current is None:
            return TickOutcome.NO_ACTION

        candidates = self._eligible_candidates(current)
        snapshots, headroom, fetch_errors = self._collect(current, candidates, now)
        self._emit_poll(current, headroom, snapshots, fetch_errors)

        active_headroom = headroom.get(current)
        trigger = auto_rank.classify_trigger(active_headroom, self._settings.threshold)
        if trigger is None:
            self._emit(NoSwitchEvent(reason="active-usage-unknown"))
            return TickOutcome.NO_ACTION
        if trigger == "below":
            # pragma: no mutate justification: classify_trigger only returns "below"
            # when headroom is measurable — the `or 0.0` fallback is unreachable, so
            # mutating it produces an identical tick.
            utilization = 100.0 - (active_headroom or 0.0)  # pragma: no mutate
            self._emit(
                NoSwitchEvent(
                    reason="below-threshold",
                    detail=f"{utilization:g}% < {self._settings.threshold:g}%",
                )
            )
            return TickOutcome.NO_ACTION
        if trigger == "proactive" and auto_rank.in_cooldown(
            state, now, self._settings.cooldown_seconds
        ):
            self._emit(NoSwitchEvent(reason="cooldown"))
            return TickOutcome.NO_ACTION
        if not candidates:
            self.blocked_long_wait = True
            self._emit(NoSwitchEvent(reason="no-candidates"))
            return TickOutcome.BLOCKED

        ordered, any_known = auto_rank.choose(
            trigger,
            candidates=candidates,
            snapshots=snapshots,
            headroom=headroom,
            active=current,
            active_headroom=active_headroom,
            threshold=self._settings.threshold,
            hysteresis_pct=self._settings.hysteresis_pct,
            strategy=self._settings.strategy,
            state=state,
            now_s=now,
        )
        if not ordered:
            return self._empty_ranking(candidates, snapshots, headroom, any_known, now)
        return self._perform_first_viable(
            trigger, current, ordered, snapshots, active_headroom, now
        )

    # -- collection ----------------------------------------------------------

    def _eligible_candidates(self, current: str) -> list[str]:
        """Enabled, unquarantined, credentialed registry names minus the active."""
        quarantined = {entry.name for entry in self._store.quarantined()}
        return [
            account.name.value
            for account in self._store.list_accounts()
            if account.name.value != current
            and account.enabled
            and account.name.value not in quarantined
            and self._files.read_credentials(self._store.account_dir(account.name)) is not None
        ]

    def _collect(
        self, current: str, candidates: list[str], now_s: float
    ) -> tuple[
        dict[str, UsageSnapshot | None],
        dict[str, float | None],
        dict[str, str],
    ]:
        """The two-phase scheduled collection: plan, escalate near the band."""
        names = [current, *candidates]
        entries = {name: self._cache.load(name) for name in names}
        reports: dict[str, UsageReport] = {}
        for name in self._plan(current, candidates, entries, now_s):
            reports[name] = self._fetch_for(name, current)
        snapshots = self._snapshots(names, entries, reports)
        if self._escalates(candidates, account_headroom(snapshots[current])):
            snapshots = self._escalate_all(names, current, entries, reports, snapshots, now_s)
        # Sampled post-fetch: a refresh may have just pushed the plan out.
        self.next_poll_due_s = self._cache.load(current).next_poll_at_s
        fetch_errors = self._fetch_errors(names, entries, reports, snapshots)
        headroom = {name: account_headroom(snapshots[name]) for name in names}
        return snapshots, headroom, fetch_errors

    def _fetch_for(self, name: str, current: str) -> UsageReport:
        return self._fetch.execute(
            name, name == current, force=True, threshold=self._settings.threshold
        )

    def _escalate_all(
        self,
        names: list[str],
        current: str,
        entries: Mapping[str, UsageCacheEntry],
        reports: dict[str, UsageReport],
        snapshots: dict[str, UsageSnapshot | None],
        now_s: float,
    ) -> dict[str, UsageSnapshot | None]:
        """Force-fetch every account whose data isn't already decision-fresh.

        Two skips besides already-fetched rows: a serve-fresh entry
        (younger than SERVE_TTL_S) is decision-grade as-is — refetching it
        every in-band tick burned ~60 req/hr/identity against the ~30/hr
        budget and self-induced the 429 freezes that blind the decision
        escalation exists to inform — and a reset-parked exhausted row is
        deliberately asleep until its reset.
        """
        for name in names:
            entry = entries[name]
            if (
                name in reports
                or cache_trust.is_fresh(entry, now_s, poll_policy.SERVE_TTL_S)
                or self._reset_parked(entry, snapshots[name], now_s)
            ):
                continue
            reports[name] = self._fetch_for(name, current)
        return self._snapshots(names, entries, reports)

    @staticmethod
    def _fetch_errors(
        names: list[str],
        entries: Mapping[str, UsageCacheEntry],
        reports: Mapping[str, UsageReport],
        snapshots: Mapping[str, UsageSnapshot | None],
    ) -> dict[str, str]:
        """Why usage stayed unknown for each account, when a cause is known."""
        errors: dict[str, str] = {}
        for name in names:
            if snapshots[name] is not None:
                continue
            report = reports.get(name)
            error = report.last_error if report and report.last_error else entries[name].last_error
            if error:
                errors[name] = error
        return errors

    def _plan(
        self,
        current: str,
        candidates: list[str],
        entries: Mapping[str, UsageCacheEntry],
        now_s: float,
    ) -> set[str]:
        """Nominate the active when due/stale/overslept plus one due candidate."""
        plan: set[str] = set()
        active = entries[current]
        if (
            active.fetched_at_s is None
            or poll_policy.poll_due(active.next_poll_at_s, now_s)
            or poll_policy.plan_oversleeps_interval(active, now_s)
            or self._stale_candidate_plan(active, now_s)
        ):
            plan.add(current)
        pick = poll_policy.due_candidate(candidates, entries, now_s)
        if pick is not None:
            plan.add(pick)
        return plan

    @staticmethod
    def _stale_candidate_plan(entry: UsageCacheEntry, now_s: float) -> bool:
        """A slow candidate-style plan left on the active slot past the age cap."""
        if entry.fetched_at_s is None:
            # pragma: no mutate justification: _plan short-circuits on
            # `fetched_at_s is None` before this helper runs — the early return's
            # value is unreachable, so mutating it changes nothing observable.
            return False  # pragma: no mutate
        headroom = account_headroom(entry.last_good)
        if headroom is None:
            # pragma: no mutate justification: an unmeasured row only needs
            # pct < 100 to count as stale — any literal below 100 is equivalent.
            pct = 0.0  # pragma: no mutate
        else:
            pct = 100.0 - headroom
        # pragma: no mutate justification: a falsy interval falls back to a value
        # under the floor either way — `or 0.0` vs any small n compares identically.
        interval_s = entry.poll_interval_s or 0.0  # pragma: no mutate
        return (
            now_s - entry.fetched_at_s >= poll_policy.ACTIVE_MAX_INTERVAL_S
            and interval_s > poll_policy.ACTIVE_MAX_INTERVAL_S
            and pct < 100.0
        )

    def _escalates(self, candidates: list[str], active_headroom: float | None) -> bool:
        """Whether the active is close enough to the band to refetch everyone."""
        if not candidates:
            return False
        if active_headroom is None:
            return True
        return (
            100.0 - active_headroom >= self._settings.threshold - poll_policy.ESCALATION_MARGIN_PCT
        )

    @staticmethod
    def _reset_parked(entry: UsageCacheEntry, snapshot: UsageSnapshot | None, now_s: float) -> bool:
        """An exhausted row holding a deliberately wide plan must not be refetched."""
        headroom = account_headroom(snapshot)
        # pragma: no mutate justification: a falsy interval falls back to a value
        # under the floor either way — `or 0.0` vs any small n compares identically.
        interval_s = entry.poll_interval_s or 0.0  # pragma: no mutate
        return (
            entry.next_poll_at_s is not None
            and now_s < entry.next_poll_at_s
            and interval_s > poll_policy.EXHAUSTED_INTERVAL_S
            and headroom is not None
            and headroom <= 0
        )

    @staticmethod
    def _snapshots(
        names: list[str],
        entries: Mapping[str, UsageCacheEntry],
        reports: Mapping[str, UsageReport],
    ) -> dict[str, UsageSnapshot | None]:
        """Fresh report for fetched accounts, last_good for the rest."""
        return {
            name: reports[name].snapshot if name in reports else entries[name].last_good
            for name in names
        }

    def _emit_poll(
        self,
        current: str,
        headroom: Mapping[str, float | None],
        snapshots: Mapping[str, UsageSnapshot | None],
        fetch_errors: dict[str, str],
    ) -> None:
        windows = {
            name: {label: pct for label, pct, _ in relevant_windows(snapshot)}
            for name, snapshot in snapshots.items()
            if snapshot is not None
        }
        self._emit(
            PollEvent(
                active=current,
                headroom=dict(headroom),
                threshold=self._settings.threshold,
                fetch_errors=fetch_errors,
                windows={n: w for n, w in windows.items() if w},
            )
        )

    # -- empty-ranking outcomes -----------------------------------------------

    def _empty_ranking(
        self,
        candidates: list[str],
        snapshots: Mapping[str, UsageSnapshot | None],
        headroom: Mapping[str, float | None],
        any_known: bool,
        now_s: float,
    ) -> TickOutcome:
        if not any_known:
            self._emit(
                NoSwitchEvent(reason="no-comparison", detail="no candidate has readable usage")
            )
            return TickOutcome.BLOCKED
        # "All exhausted" only when literally true: every candidate measured
        # and at its limit. Anything else can become viable at any moment.
        truly_exhausted = all(
            (h := headroom.get(name)) is not None and h <= 0 for name in candidates
        )
        if not truly_exhausted:
            self._emit(
                NoSwitchEvent(
                    reason="no-qualifying-candidate",
                    detail=(
                        "no candidate is below the threshold and better than the "
                        "active account by the hysteresis margin, or usage is "
                        "unreadable this tick"
                    ),
                )
            )
            return TickOutcome.BLOCKED
        self.blocked_long_wait = True
        earliest = auto_rank.earliest_recovery_epoch(snapshots, now_s)
        if earliest is not None:
            self.sleep_until_s = earliest + poll_policy.RESET_SLACK_S
        self._emit(AllExhaustedEvent(earliest_reset_at_s=earliest))
        return TickOutcome.BLOCKED

    # -- freshen + perform ------------------------------------------------------

    def _perform_first_viable(
        self,
        trigger: str,
        current: str,
        ordered: list[str],
        snapshots: Mapping[str, UsageSnapshot | None],
        active_headroom: float | None,
        now_s: float,
    ) -> TickOutcome:
        """Freshen each ranked target in order; switch onto the first live one."""
        left_recovery = auto_rank.binding_recovery_epoch(snapshots.get(current), now_s)
        # pragma: no mutate justification: the flag is only read as a truth value —
        # None is falsy-equivalent to False here.
        transient = False  # pragma: no mutate
        for name in ordered:
            if self._dry_run:
                self._emit(
                    SwitchEvent(trigger=trigger, from_name=current, to_name=name, dry_run=True)
                )
                return TickOutcome.SWITCHED
            status = self._freshen.execute(name)
            if status == "dead":
                self._quarantine.execute(AccountName(name))
                self._emit(QuarantinedEvent(name=name, reason="invalid_grant"))
                continue
            if status == "transient":
                transient = True
                continue
            return self._perform(trigger, current, name, active_headroom, left_recovery)
        if transient:
            self._emit(ErrorEvent(message="could not freshen any candidate (network?)"))
            return TickOutcome.ERROR
        self._emit(NoSwitchEvent(reason="no-viable-target"))
        return TickOutcome.BLOCKED

    def _perform(
        self,
        trigger: str,
        current: str,
        name: str,
        active_headroom: float | None,
        left_recovery: float,
    ) -> TickOutcome:
        """The locked recheck → switch → record transaction."""
        with self._auto_state.locked():
            state = self._auto_state.load()
            now_s = self._clock.now_epoch_s()
            if trigger == "proactive" and auto_rank.in_cooldown(
                state, now_s, self._settings.cooldown_seconds
            ):
                self._emit(NoSwitchEvent(reason="cooldown"))
                return TickOutcome.NO_ACTION
            result = self._switch.execute(AccountName(name), dry_run=False)
            if result.outcome != "switched":
                self._emit(NoSwitchEvent(reason="already-active", detail=result.outcome))
                return TickOutcome.NO_ACTION
            self._auto_state.save(
                AutoState(
                    last_switch_at_s=now_s,
                    last_switch_from=result.previous or current,
                    last_switch_to=name,
                    left_headroom=active_headroom,
                    left_recovery_at_s=(None if left_recovery == math.inf else left_recovery),
                )
            )
        self._emit(
            SwitchEvent(
                trigger=trigger,
                from_name=result.previous or current,
                to_name=name,
            )
        )
        return TickOutcome.SWITCHED
