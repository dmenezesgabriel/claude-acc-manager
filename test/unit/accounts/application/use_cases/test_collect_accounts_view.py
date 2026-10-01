"""Unit tests for accounts.application.use_cases.collect_accounts_view."""

from dataclasses import replace
from pathlib import Path

import pytest
from support.controllable_clock import ControllableClock
from support.fake_account_dir import FakeAccountDir
from support.fake_active_slot import FakeActiveSlot
from support.in_memory_account_store import InMemoryAccountStore
from support.in_memory_usage_cache import InMemoryUsageCache

from claude_acc_manager.accounts.application.use_cases.collect_accounts_view import (
    AccountsView,
    CollectAccountsView,
)
from claude_acc_manager.accounts.domain.entities import Account, QuarantineEntry
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.usage.domain.usage_cache_entry import EMPTY_USAGE_CACHE_ENTRY
from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot, UsageWindow

_SNAPSHOT = UsageSnapshot(
    five_hour=UsageWindow(pct=10.0, resets_at=None), seven_day=None, scoped=()
)


def _account(name: str, account_uuid: str, *, enabled: bool = True) -> Account:
    return Account(
        name=AccountName(name),
        email=f"{name}@example.com",
        account_uuid=account_uuid,
        organization_uuid="org-456",
        organization_name="Test Org",
        added_at="2026-09-10T12:00:00Z",
        enabled=enabled,
    )


def _live_config(account_uuid: str, email: str = "live@example.com") -> dict[str, object]:
    return {"oauthAccount": {"emailAddress": email, "accountUuid": account_uuid}}


def _use_case(
    *,
    store: InMemoryAccountStore | None = None,
    slot: FakeActiveSlot | None = None,
    files: FakeAccountDir | None = None,
    cache: InMemoryUsageCache | None = None,
    clock: ControllableClock | None = None,
    tmp_path: Path,
) -> tuple[
    CollectAccountsView,
    InMemoryAccountStore,
    FakeActiveSlot,
    FakeAccountDir,
    InMemoryUsageCache,
    ControllableClock,
]:
    store = store or InMemoryAccountStore(tmp_path)
    slot = slot or FakeActiveSlot()
    files = files or FakeAccountDir()
    cache = cache or InMemoryUsageCache()
    clock = clock or ControllableClock(now_epoch_s=1_000_000.0)
    return CollectAccountsView(store, slot, files, cache, clock), store, slot, files, cache, clock


class TestEmptyAndOrdering:
    def test_an_empty_registry_gives_an_empty_view(self, tmp_path: Path):
        use_case, _, _, _, _, clock = _use_case(tmp_path=tmp_path)

        view = use_case.execute()

        assert view == AccountsView(
            active_name=None,
            live_identity=None,
            accounts=(),
            taken_at_s=clock.now_epoch_s(),
        )

    def test_accounts_appear_in_registry_order(self, tmp_path: Path):
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("b", "uuid-b"))
        store.upsert(_account("a", "uuid-a"))
        use_case, _, _, _, _, _ = _use_case(store=store, tmp_path=tmp_path)

        view = use_case.execute()

        assert [row.account.name.value for row in view.accounts] == ["b", "a"]


class TestLiveResolution:
    def test_the_active_flag_follows_the_live_uuid_not_the_pointer(self, tmp_path: Path):
        # arrange — the registry pointer says "b" but the live slot holds "a"
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("a", "uuid-a"))
        store.upsert(_account("b", "uuid-b"))
        store.set_active(AccountName("b"))
        slot = FakeActiveSlot(config=_live_config("uuid-a"))
        use_case, _, _, _, _, _ = _use_case(store=store, slot=slot, tmp_path=tmp_path)

        # act
        view = use_case.execute()

        # assert
        assert view.active_name == "a"
        flags = {row.account.name.value: row.is_active for row in view.accounts}
        assert flags == {"a": True, "b": False}

    def test_an_unmanaged_live_login_marks_nobody_active(self, tmp_path: Path):
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("a", "uuid-a"))
        slot = FakeActiveSlot(config=_live_config("uuid-foreign", email="who@else.org"))
        use_case, _, _, _, _, _ = _use_case(store=store, slot=slot, tmp_path=tmp_path)

        view = use_case.execute()

        assert view.active_name is None
        assert view.live_identity is not None
        assert view.live_identity.email == "who@else.org"
        assert [row.is_active for row in view.accounts] == [False]

    def test_no_live_login_gives_no_identity(self, tmp_path: Path):
        use_case, _, _, _, _, _ = _use_case(slot=FakeActiveSlot(config=None), tmp_path=tmp_path)

        view = use_case.execute()

        assert view.active_name is None
        assert view.live_identity is None

    def test_a_torn_oauth_block_propagates_the_value_error(self, tmp_path: Path):
        use_case, _, _, _, _, _ = _use_case(
            slot=FakeActiveSlot(config={"oauthAccount": "not-an-object"}),
            tmp_path=tmp_path,
        )

        with pytest.raises(ValueError, match="expected a JSON object"):
            use_case.execute()


class TestRowFields:
    def test_carries_quarantine_enabled_and_credential_flags(self, tmp_path: Path):
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("a", "uuid-a"))
        store.upsert(_account("b", "uuid-b", enabled=False))
        store.set_quarantined(
            QuarantineEntry("b", "permanent_auth_error", "2026-09-10T12:00:00Z", None)
        )
        files = FakeAccountDir()
        files.put(store.account_dir(AccountName("a")), credentials={"t": 1})
        use_case, _, _, _, _, _ = _use_case(store=store, files=files, tmp_path=tmp_path)

        view = use_case.execute()

        by_name = {row.account.name.value: row for row in view.accounts}
        assert by_name["a"].is_quarantined is False
        assert by_name["a"].has_credentials is True
        assert by_name["b"].is_quarantined is True
        assert by_name["b"].account.enabled is False
        assert by_name["b"].has_credentials is False

    def test_carries_each_accounts_cache_entry(self, tmp_path: Path):
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("a", "uuid-a"))
        store.upsert(_account("b", "uuid-b"))
        cache = InMemoryUsageCache()
        entry = replace(EMPTY_USAGE_CACHE_ENTRY, last_good=_SNAPSHOT, fetched_at_s=42.0)
        cache.save("a", entry)
        use_case, _, _, _, _, _ = _use_case(store=store, cache=cache, tmp_path=tmp_path)

        view = use_case.execute()

        by_name = {row.account.name.value: row for row in view.accounts}
        assert by_name["a"].usage == entry
        assert by_name["b"].usage == EMPTY_USAGE_CACHE_ENTRY

    def test_taken_at_is_the_clock_reading(self, tmp_path: Path):
        clock = ControllableClock(now_epoch_s=1_234_567.0)
        use_case, _, _, _, _, _ = _use_case(clock=clock, tmp_path=tmp_path)

        assert use_case.execute().taken_at_s == 1_234_567.0
