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
from claude_acc_manager.accounts.application.use_cases.list_accounts import ListAccounts
from claude_acc_manager.accounts.application.use_cases.quarantine_account import (
    QuarantineAccount,
)
from claude_acc_manager.accounts.application.use_cases.remove_account import RemoveAccount
from claude_acc_manager.accounts.application.use_cases.status_account import StatusAccount
from claude_acc_manager.accounts.application.use_cases.switch_account import SwitchAccount
from claude_acc_manager.accounts.infrastructure.account_credential_store import (
    AccountCredentialStore,
)
from claude_acc_manager.accounts.infrastructure.account_dir_files import AccountDirFiles
from claude_acc_manager.accounts.infrastructure.active_slot import ActiveSlotAdapter
from claude_acc_manager.accounts.infrastructure.claude_locks import MkdirClaudeLock
from claude_acc_manager.accounts.infrastructure.claude_login_launcher import ClaudeLoginLauncher
from claude_acc_manager.accounts.infrastructure.file_account_store import FileAccountStore
from claude_acc_manager.accounts.infrastructure.path_resolver import data_home
from claude_acc_manager.accounts.infrastructure.system_clock import SystemClock
from claude_acc_manager.accounts.infrastructure.unclaimed_store import FileUnclaimedStore
from claude_acc_manager.cli import UseCases, run
from claude_acc_manager.usage.application.use_cases.fetch_account_usage import FetchAccountUsage
from claude_acc_manager.usage.infrastructure.anthropic_oauth import (
    AnthropicTokenRefresher,
    AnthropicUsageApi,
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
    return UseCases(
        add=AddAccount(ClaudeLoginLauncher(), files, store, clock),
        remove=RemoveAccount(store),
        list_accounts=ListAccounts(store),
        status=StatusAccount(slot, store),
        fetch_usage=FetchAccountUsage(
            AnthropicUsageApi(transport),
            AnthropicTokenRefresher(transport),
            AccountCredentialStore(store, slot),
            usage_cache,
            UsageSystemClock(),
        ),
        switch=SwitchAccount(
            store,
            slot,
            files,
            FileUnclaimedStore(store_root, clock),
            MkdirClaudeLock(env=env, home=home),
            clock,
        ),
        quarantine=QuarantineAccount(store, clock),
        account_store=store,
        account_files=files,
        usage_cache=usage_cache,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point: build the use cases from the environment, then dispatch."""
    return run(argv, build_use_cases(os.environ, Path.home()))


if __name__ == "__main__":
    sys.exit(main())
