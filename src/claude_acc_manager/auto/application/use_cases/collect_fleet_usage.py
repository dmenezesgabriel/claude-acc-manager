"""CollectFleetUsage — the tick's scheduled collection stage.

One ``execute`` gathers everything the decide stage ranks on: the eligible
candidates (enabled, unquarantined, credentialed registry names minus the
active), the scheduled plan (active-when-due plus one stalest candidate,
escalating to everyone when the active nears the threshold band), the
per-account snapshots/headroom/fetch_errors, the post-fetch next-poll hint
the loop reads, and the ready-to-emit ``PollEvent``.

Split out of ``AutoEngine`` (AUD-002): the engine orchestrates the tick;
this use case owns the collection stage's orchestration over
store/files/cache/fetch.

Example:
    collector = CollectFleetUsage(settings=..., store=..., account_files=...,
                                  usage_cache=..., fetch=...)
    collected = collector.execute("personal", now_s)
    emit(collected.poll_event)
"""

from collections.abc import Mapping

from claude_acc_manager.accounts.application.ports import (
    AccountDirPort,
    AccountStorePort,
)
from claude_acc_manager.accounts.domain.services.switch_selection import HeadroomMap
from claude_acc_manager.auto.application.ports import (
    FleetCollection,
    FleetCollectorPort,
)
from claude_acc_manager.auto.domain.auto_event import PollEvent
from claude_acc_manager.settings.domain.settings_spec import AutoSettings
from claude_acc_manager.usage.application.ports import UsageCachePort, UsageFetchPort
from claude_acc_manager.usage.domain.services import cache_trust, poll_policy
from claude_acc_manager.usage.domain.services.headroom import (
    account_headroom,
    relevant_windows,
)
from claude_acc_manager.usage.domain.usage_cache_entry import UsageCacheEntry
from claude_acc_manager.usage.domain.usage_report import UsageReport
from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot


class CollectFleetUsage(FleetCollectorPort):
    """Collect the fleet's decision-grade usage for one tick.

    Example:
        collected = collector.execute("personal", now_s)
        emit(collected.poll_event)
    """

    def __init__(
        self,
        *,
        settings: AutoSettings,
        store: AccountStorePort,
        account_files: AccountDirPort,
        usage_cache: UsageCachePort,
        fetch: UsageFetchPort,
    ) -> None:
        """Store the injected settings and ports."""
        self._settings = settings
        self._store = store
        self._files = account_files
        self._cache = usage_cache
        self._fetch = fetch

    def execute(self, current: str, now_s: float) -> FleetCollection:
        """The two-phase scheduled collection: plan, escalate near the band.

        Example:
            collected = self.execute("personal", now_s)
        """
        candidates = self._eligible_candidates(current)
        names = [current, *candidates]
        entries = {name: self._cache.load(name) for name in names}
        reports: dict[str, UsageReport] = {}
        for name in self._plan(current, candidates, entries, now_s):
            reports[name] = self._fetch_for(name, current)
        snapshots = self._snapshots(names, entries, reports)
        if self._escalates(candidates, account_headroom(snapshots[current])):
            snapshots = self._escalate_all(names, current, entries, reports, snapshots, now_s)
        # Sampled post-fetch: a refresh may have just pushed the plan out.
        next_poll_due_s = self._cache.load(current).next_poll_at_s
        fetch_errors = self._fetch_errors(names, entries, reports, snapshots)
        headroom = {name: account_headroom(snapshots[name]) for name in names}
        return FleetCollection(
            candidates=candidates,
            snapshots=snapshots,
            headroom=headroom,
            next_poll_due_s=next_poll_due_s,
            poll_event=self._poll_event(current, headroom, snapshots, fetch_errors),
        )

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

    def _poll_event(
        self,
        current: str,
        headroom: HeadroomMap,
        snapshots: Mapping[str, UsageSnapshot | None],
        fetch_errors: dict[str, str],
    ) -> PollEvent:
        windows = {
            name: {label: pct for label, pct, _ in relevant_windows(snapshot)}
            for name, snapshot in snapshots.items()
            if snapshot is not None
        }
        return PollEvent(
            active=current,
            headroom=dict(headroom),
            threshold=self._settings.threshold,
            fetch_errors=fetch_errors,
            windows={n: w for n, w in windows.items() if w},
        )
