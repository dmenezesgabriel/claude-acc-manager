"""Composition root for the ``cam`` command.

The one module allowed to import concrete infrastructure adapters: it wires
them from the process environment and hands them to the transport-only
``cli.run`` (ADR-0010 — ``cli`` itself reaches components only through
use cases). ``[project.scripts] cam`` points here.
"""

import os
import sys
from collections.abc import Mapping, Sequence
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
from claude_acc_manager.accounts.infrastructure.account_credential_store import (
    AccountCredentialStore,
)
from claude_acc_manager.accounts.infrastructure.account_dir_files import AccountDirFiles
from claude_acc_manager.accounts.infrastructure.active_slot import ActiveSlotAdapter
from claude_acc_manager.accounts.infrastructure.claude_contract_probe import (
    SubprocessClaudeContractProbe,
)
from claude_acc_manager.accounts.infrastructure.claude_locks import MkdirClaudeLock
from claude_acc_manager.accounts.infrastructure.claude_login_launcher import ClaudeLoginLauncher
from claude_acc_manager.accounts.infrastructure.file_account_store import FileAccountStore
from claude_acc_manager.accounts.infrastructure.ops_lock import FlockOpsLock
from claude_acc_manager.accounts.infrastructure.path_resolver import data_home
from claude_acc_manager.accounts.infrastructure.system_clock import SystemClock
from claude_acc_manager.accounts.infrastructure.unclaimed_store import FileUnclaimedStore
from claude_acc_manager.auto.application.use_cases.freshen_target import FreshenTarget
from claude_acc_manager.auto.infrastructure.file_auto_state import FileAutoState
from claude_acc_manager.cli import ProcessContext, UseCases, run
from claude_acc_manager.settings.application.use_cases.list_settings import ListSettings
from claude_acc_manager.settings.application.use_cases.load_settings import LoadSettings
from claude_acc_manager.settings.application.use_cases.set_setting import SetSetting
from claude_acc_manager.settings.application.use_cases.unset_setting import UnsetSetting
from claude_acc_manager.settings.infrastructure.file_settings import FileSettings
from claude_acc_manager.shared.container import running_in_container
from claude_acc_manager.usage.application.use_cases.fetch_account_usage import FetchAccountUsage
from claude_acc_manager.usage.infrastructure.anthropic_oauth import (
    AnthropicTokenRefresher,
    AnthropicUsageApi,
)
from claude_acc_manager.usage.infrastructure.claude_contract_probe import (
    SubprocessClaudeContractProbe as UsageSubprocessClaudeContractProbe,
)
from claude_acc_manager.usage.infrastructure.file_usage_cache import FileUsageCache
from claude_acc_manager.usage.infrastructure.http_transport import UrllibHttpTransport
from claude_acc_manager.usage.infrastructure.system_clock import SystemClock as UsageSystemClock

_STORE_DIRNAME = "claude-acc-manager"


def build_use_cases(env: Mapping[str, str], home: Path) -> UseCases:
    """Wire the concrete adapters against the store dir (docs/architecture.md §3 layout)."""
    store_root = data_home(env, home) / _STORE_DIRNAME
    store = FileAccountStore(store_root)
    transport = UrllibHttpTransport()
    slot = ActiveSlotAdapter(env, home)
    files = AccountDirFiles()
    clock = SystemClock()
    usage_cache = FileUsageCache(store_root)
    settings = FileSettings(store_root)
    ops = FlockOpsLock(store_root)
    return UseCases(
        add=AddAccount(ClaudeLoginLauncher(), files, store, clock, ops),
        remove=RemoveAccount(store, ops),
        list_accounts=ListAccounts(store),
        collect_view=CollectAccountsView(store, slot, files, usage_cache, UsageSystemClock()),
        status=StatusAccount(slot, store),
        fetch_usage=FetchAccountUsage(
            AnthropicUsageApi(transport),
            AnthropicTokenRefresher(transport),
            AccountCredentialStore(store, slot),
            usage_cache,
            UsageSystemClock(),
            UsageSubprocessClaudeContractProbe(),
            threshold=settings.load().threshold,
        ),
        switch=SwitchAccount(
            store,
            slot,
            files,
            FileUnclaimedStore(store_root, clock),
            MkdirClaudeLock(env=env, home=home),
            clock,
            ops,
            SubprocessClaudeContractProbe(),
        ),
        quarantine_dead_lineage=QuarantineDeadLineage(store, files, clock),
        set_enabled=SetAccountEnabled(store),
        freshen_target=FreshenTarget(
            AnthropicTokenRefresher(transport),
            AccountCredentialStore(store, slot),
            UsageSystemClock(),
            UsageSubprocessClaudeContractProbe(),
        ),
        load_settings=LoadSettings(settings),
        set_setting=SetSetting(settings),
        unset_setting=UnsetSetting(settings),
        list_settings=ListSettings(settings),
        account_store=store,
        account_files=files,
        usage_cache=usage_cache,
        usage_clock=UsageSystemClock(),
        settings=settings,
        auto_state=FileAutoState(store_root),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point: build the use cases from the environment, then dispatch."""
    process = ProcessContext(
        euid=os.geteuid(),
        in_container=running_in_container(os.environ, Path("/")),
        interactive=sys.stdin.isatty() and sys.stdout.isatty(),
    )
    return run(argv, build_use_cases(os.environ, Path.home()), process=process)


if __name__ == "__main__":
    sys.exit(main())
