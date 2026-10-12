"""auto_engine — the auto-switch engine: poll, decide, switch, record.

One ``tick()`` evaluates the fleet once: resolve the live account, run the
scheduled collection through ``FleetCollectorPort`` (active-when-due plus
one stalest candidate, escalating to everyone when the active nears the
threshold band), classify the trigger, rank candidates under the anti-flap
gates, freshen the pick's parked credential, then switch under the state
lock and record the departure snapshot the no-return guard needs next tick.

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
    ActiveIdentityPort,
    LineageQuarantinePort,
    SwitchExecutorPort,
)
from claude_acc_manager.accounts.domain.services.switch_selection import HeadroomMap
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.auto.application.ports import (
    AutoStatePort,
    FleetCollectorPort,
    FreshenPort,
)
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
from claude_acc_manager.usage.application.ports import ClockPort
from claude_acc_manager.usage.domain.services import poll_policy
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
        collector: FleetCollectorPort,
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
        self._collector = collector
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

        collected = self._collector.execute(current, now)
        self.next_poll_due_s = collected.next_poll_due_s
        self._emit(collected.poll_event)

        candidates = collected.candidates
        snapshots = collected.snapshots
        headroom = collected.headroom
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

    # -- empty-ranking outcomes -----------------------------------------------

    def _empty_ranking(
        self,
        candidates: list[str],
        snapshots: Mapping[str, UsageSnapshot | None],
        headroom: HeadroomMap,
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
