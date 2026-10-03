"""Fake-backed ``UseCases`` builder shared by CLI and TUI tests.

One call wires every use case over named fakes, so a test overrides exactly
the seam it cares about (e.g. ``usage_api`` to steer fetch outcomes) and
inherits inert defaults for the rest.
"""

from pathlib import Path

from claude_acc_manager.accounts.application.use_cases.add_account import AddAccount
from claude_acc_manager.accounts.application.use_cases.collect_accounts_view import (
    CollectAccountsView,
)
from claude_acc_manager.accounts.application.use_cases.list_accounts import ListAccounts
from claude_acc_manager.accounts.application.use_cases.quarantine_dead_lineage import (
    QuarantineDeadLineage,
)
from claude_acc_manager.accounts.application.use_cases.remove_account import RemoveAccount
from claude_acc_manager.accounts.application.use_cases.set_account_enabled import (
    SetAccountEnabled,
)
from claude_acc_manager.accounts.application.use_cases.status_account import StatusAccount
from claude_acc_manager.accounts.application.use_cases.switch_account import SwitchAccount
from claude_acc_manager.accounts.domain.entities import Account
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.auto.application.use_cases.freshen_target import FreshenTarget
from claude_acc_manager.cli.context import UseCases
from claude_acc_manager.settings.application.use_cases.list_settings import ListSettings
from claude_acc_manager.settings.application.use_cases.load_settings import LoadSettings
from claude_acc_manager.settings.application.use_cases.set_setting import SetSetting
from claude_acc_manager.settings.application.use_cases.unset_setting import UnsetSetting
from claude_acc_manager.shared.claude_contract import contract_for_version
from claude_acc_manager.usage.application.use_cases.fetch_account_usage import (
    FetchAccountUsage,
)
from claude_acc_manager.usage.domain.oauth_credential import StoredOAuthCredential
from claude_acc_manager.usage.domain.usage_snapshot import (
    UsageSnapshot,
    UsageWindow,
)
from support.controllable_clock import ControllableClock
from support.fake_account_dir import FakeAccountDir
from support.fake_active_slot import FakeActiveSlot
from support.fake_claude_contract import FakeClaudeContractProbe
from support.fake_claude_locks import FakeClaudeLocks
from support.fake_clock import FakeClock
from support.fake_credential_store import FakeCredentialStore
from support.fake_login_launcher import FakeLoginLauncher
from support.fake_ops_lock import FakeOpsLock
from support.fake_token_refresher import FakeTokenRefresher
from support.fake_unclaimed_store import FakeUnclaimedStore
from support.fake_usage_api import FakeUsageApi
from support.in_memory_account_store import InMemoryAccountStore
from support.in_memory_auto_state import InMemoryAutoState
from support.in_memory_settings import InMemorySettings
from support.in_memory_usage_cache import InMemoryUsageCache

SEEDED_CREDENTIALS: dict[str, object] = {"claudeAiOauth": {"accessToken": "tok"}}
SEEDED_CONFIG: dict[str, object] = {
    "oauthAccount": {"emailAddress": "user@example.com", "accountUuid": "acc-123"},
}
SEEDED_SNAPSHOT = UsageSnapshot(
    five_hour=UsageWindow(pct=10.0, resets_at=None), seven_day=None, scoped=()
)


def make_fetch_usage(
    *,
    usage_api: FakeUsageApi | None = None,
    refresher: FakeTokenRefresher | None = None,
    credentials: FakeCredentialStore | None = None,
    usage_cache: InMemoryUsageCache | None = None,
    usage_clock: ControllableClock | None = None,
    threshold: float = 90.0,
    contract_probe: FakeClaudeContractProbe | None = None,
) -> FetchAccountUsage:
    """A FetchAccountUsage over fakes; share *usage_cache*/*usage_clock* to observe them."""
    return FetchAccountUsage(
        usage_api or FakeUsageApi(snapshot=SEEDED_SNAPSHOT),
        refresher or FakeTokenRefresher(),
        credentials or FakeCredentialStore(),
        usage_cache or InMemoryUsageCache(),
        usage_clock or ControllableClock(now_epoch_s=1_000_000.0),
        contract_probe or FakeClaudeContractProbe(contract_for_version((2, 1, 288))),
        threshold=threshold,
    )


def make_use_cases(
    tmp_path: Path,
    *,
    store: InMemoryAccountStore | None = None,
    launcher: FakeLoginLauncher | None = None,
    list_accounts: ListAccounts | None = None,
    collect_view: CollectAccountsView | None = None,
    reader: FakeAccountDir | None = None,
    slot: FakeActiveSlot | None = None,
    ops: FakeOpsLock | None = None,
    fetch_usage: FetchAccountUsage | None = None,
    usage_cache: InMemoryUsageCache | None = None,
    usage_clock: ControllableClock | None = None,
    settings: InMemorySettings | None = None,
    credentials: FakeCredentialStore | None = None,
    freshen_target: FreshenTarget | None = None,
    auto_state: InMemoryAutoState | None = None,
    contract_probe: FakeClaudeContractProbe | None = None,
) -> UseCases:
    """Wire UseCases over named fakes; pass shared fakes to observe across cases."""
    store = store or InMemoryAccountStore(tmp_path)
    slot = slot or FakeActiveSlot(config=None)
    if reader is None:
        reader = FakeAccountDir()
        reader.put(
            tmp_path / "accounts" / "work", credentials=SEEDED_CREDENTIALS, config=SEEDED_CONFIG
        )
    clock = FakeClock()
    ops = ops or FakeOpsLock()
    resolved_cache = usage_cache or InMemoryUsageCache()
    resolved_clock = usage_clock or ControllableClock(now_epoch_s=1_000_000.0)
    resolved_settings = settings or InMemorySettings(tmp_path)
    resolved_credentials = credentials or FakeCredentialStore()
    return UseCases(
        add=AddAccount(launcher or FakeLoginLauncher(), reader, store, clock, ops),
        remove=RemoveAccount(store, ops),
        list_accounts=list_accounts or ListAccounts(store),
        collect_view=collect_view
        or CollectAccountsView(store, slot, reader, resolved_cache, resolved_clock),
        status=StatusAccount(slot, store),
        fetch_usage=fetch_usage
        or make_fetch_usage(credentials=resolved_credentials, usage_clock=resolved_clock),
        switch=SwitchAccount(
            store,
            slot,
            reader,
            FakeUnclaimedStore(),
            FakeClaudeLocks(),
            clock,
            ops,
            contract_probe or FakeClaudeContractProbe(contract_for_version((2, 1, 288))),
        ),
        quarantine_dead_lineage=QuarantineDeadLineage(store, reader, clock),
        set_enabled=SetAccountEnabled(store),
        freshen_target=freshen_target
        or FreshenTarget(
            FakeTokenRefresher(),
            resolved_credentials,
            resolved_clock,
            FakeClaudeContractProbe(contract_for_version((2, 1, 288))),
        ),
        load_settings=LoadSettings(resolved_settings),
        set_setting=SetSetting(resolved_settings),
        unset_setting=UnsetSetting(resolved_settings),
        list_settings=ListSettings(resolved_settings),
        account_store=store,
        account_files=reader,
        usage_cache=resolved_cache,
        usage_clock=resolved_clock,
        settings=resolved_settings,
        auto_state=auto_state or InMemoryAutoState(),
    )


def make_account(name: str, account_uuid: str = "acc-x") -> Account:
    """A registry Account the tests seed stores with."""
    return Account(
        name=AccountName(name),
        email=f"{name}@example.com",
        account_uuid=account_uuid,
        organization_uuid=None,
        organization_name=None,
        added_at="2026-09-10T12:00:00Z",
        enabled=True,
    )


def credentials_for(name: str) -> dict[str, object]:
    """A parked ``.credentials.json`` blob whose tokens name the account."""
    return {"claudeAiOauth": {"accessToken": f"at-{name}", "refreshToken": f"rt-{name}"}}


def stored_credential(*, expires_at_ms: float | None = None) -> StoredOAuthCredential:
    """The parsed credential shape the usage use case reads."""
    return StoredOAuthCredential(
        access_token="at-old", refresh_token="rt-old", expires_at_ms=expires_at_ms
    )
