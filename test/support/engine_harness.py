"""AutoEngine wired over named fakes — the hermetic tick/loop rig.

Shared by the tick pipeline tests and the run_loop tests: one builder
exposes every port knob (registry, credentials, identity, cache rows,
fresh reports, freshen/switch outcomes, persisted state, settings,
dry-run, event sink) so each test only names what varies.
"""

import datetime as dt
from collections.abc import Callable
from pathlib import Path

from claude_acc_manager.accounts.application.ports import (
    ActiveAccountStatus,
    SwitchResult,
)
from claude_acc_manager.accounts.domain.entities import Account
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.auto.application.auto_engine import AutoEngine
from claude_acc_manager.auto.application.ports import FreshenStatus
from claude_acc_manager.auto.domain.auto_event import AutoEvent, TickOutcome
from claude_acc_manager.auto.domain.auto_state import EMPTY_AUTO_STATE, AutoState
from claude_acc_manager.settings.domain.settings_spec import AutoSettings
from claude_acc_manager.usage.domain.usage_cache_entry import UsageCacheEntry
from claude_acc_manager.usage.domain.usage_report import UsageReport
from claude_acc_manager.usage.domain.usage_snapshot import (
    UsageSnapshot,
    UsageWindow,
)
from support.controllable_clock import ControllableClock
from support.fake_account_dir import FakeAccountDir
from support.fake_active_identity import FakeActiveIdentity
from support.fake_freshen import FakeFreshen
from support.fake_lineage_quarantine import FakeLineageQuarantine
from support.fake_switch_executor import FakeSwitchExecutor
from support.fake_usage_fetch import FakeUsageFetch
from support.in_memory_account_store import InMemoryAccountStore
from support.in_memory_auto_state import InMemoryAutoState
from support.in_memory_usage_cache import InMemoryUsageCache

NOW_S = 1_700_000_000.0


def iso(epoch_s: float) -> str:
    """Format *epoch_s* as the UTC ISO-8601 the API returns."""
    return dt.datetime.fromtimestamp(epoch_s, dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def snap(pct: float, reset_s: float | None = None) -> UsageSnapshot:
    """A snapshot with one 5h window at *pct* utilization."""
    return UsageSnapshot(
        five_hour=UsageWindow(pct=pct, resets_at=iso(reset_s) if reset_s else None),
        seven_day=None,
        scoped=(),
    )


def report(snapshot: UsageSnapshot | None, last_error: str | None = None) -> UsageReport:
    """A fresh-fetch report carrying *snapshot*."""
    return UsageReport(snapshot, stale=False, last_error=last_error, permanent_auth_error=False)


def account(name: str, enabled: bool = True) -> Account:
    return Account(
        AccountName(name),
        email=f"{name}@example.com",
        account_uuid=f"uuid-{name}",
        organization_uuid=None,
        organization_name=None,
        added_at="2026-09-10T12:00:00Z",
        enabled=enabled,
    )


def entry(
    snapshot: UsageSnapshot | None,
    *,
    fetched_at_s: float | None = NOW_S - 400.0,
    next_poll_at_s: float | None = NOW_S - 1.0,
    poll_interval_s: float | None = 300.0,
) -> UsageCacheEntry:
    """A cache row that is past its plan (due) unless overridden."""
    return UsageCacheEntry(
        last_good=snapshot,
        fetched_at_s=fetched_at_s,
        consecutive_failures=0,
        last_error=None,
        backoff_until_s=None,
        last_429_at_s=None,
        next_poll_at_s=next_poll_at_s,
        poll_interval_s=poll_interval_s,
    )


def identity(managed_as: str | None) -> ActiveAccountStatus:
    """The live login resolved to a managed name (or not)."""
    return ActiveAccountStatus(
        email="live@example.com",
        account_uuid="uuid-live",
        organization_uuid=None,
        organization_name=None,
        managed_as=managed_as,
    )


class EngineHarness:
    """Builds the engine over named fakes with knobs for each seam."""

    def __init__(
        self,
        *,
        accounts: list[Account],
        credentialed: set[str],
        identity: ActiveAccountStatus | None,
        cache_rows: dict[str, UsageCacheEntry] | None = None,
        reports: dict[str, UsageReport] | None = None,
        freshen: dict[str, FreshenStatus] | None = None,
        switch_result: SwitchResult | None = None,
        state: AutoState = EMPTY_AUTO_STATE,
        auto_state_port: InMemoryAutoState | None = None,
        settings: AutoSettings | None = None,
        dry_run: bool = False,
        emit: Callable[[AutoEvent], None] | None = None,
    ) -> None:
        self.store = InMemoryAccountStore(Path("/store"))
        for account in accounts:
            self.store.upsert(account)
        self.files = FakeAccountDir()
        for name in credentialed:
            self.files.put(self.store.account_dir(AccountName(name)), credentials={"k": "v"})
        self.cache = InMemoryUsageCache()
        for name, entry in (cache_rows or {}).items():
            self.cache.save(name, entry)
        self.fetch = FakeUsageFetch(reports)
        self.freshen = FakeFreshen(freshen)
        self.quarantine = FakeLineageQuarantine()
        self.executor = FakeSwitchExecutor(
            switch_result or SwitchResult(outcome="switched", target="?", previous=None)
        )
        self.auto_state = auto_state_port or InMemoryAutoState(state)
        self.clock = ControllableClock(NOW_S)
        self.events: list[AutoEvent] = []
        self.engine = AutoEngine(
            settings=settings or AutoSettings(),
            active_identity=FakeActiveIdentity(identity),
            store=self.store,
            account_files=self.files,
            usage_cache=self.cache,
            fetch=self.fetch,
            freshen=self.freshen,
            quarantine=self.quarantine,
            switch_executor=self.executor,
            auto_state=self.auto_state,
            clock=self.clock,
            emit=emit or self.events.append,
            dry_run=dry_run,
        )

    def tick(self) -> TickOutcome:
        return self.engine.tick()
