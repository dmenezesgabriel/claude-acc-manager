"""Composition root for the ``cam`` command.

The one module allowed to import concrete infrastructure adapters: it wires
them from the process environment and hands them to the transport-only
``cli.run`` (plan §4.1 rule 8 — ``cli`` itself reaches components only through
use cases). ``[project.scripts] cam`` points here.
"""

import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from claude_acc_manager.accounts.application.use_cases.add_account import AddAccount
from claude_acc_manager.accounts.application.use_cases.list_accounts import ListAccounts
from claude_acc_manager.accounts.application.use_cases.remove_account import RemoveAccount
from claude_acc_manager.accounts.application.use_cases.status_account import StatusAccount
from claude_acc_manager.accounts.infrastructure.account_dir_reader import AccountDirReader
from claude_acc_manager.accounts.infrastructure.active_slot import ActiveSlotAdapter
from claude_acc_manager.accounts.infrastructure.claude_login_launcher import ClaudeLoginLauncher
from claude_acc_manager.accounts.infrastructure.file_account_store import FileAccountStore
from claude_acc_manager.accounts.infrastructure.path_resolver import data_home
from claude_acc_manager.accounts.infrastructure.system_clock import SystemClock
from claude_acc_manager.cli import UseCases, run

_STORE_DIRNAME = "claude-acc-manager"


def build_use_cases(env: Mapping[str, str], home: Path) -> UseCases:
    """Wire the concrete adapters against the store dir (plan §4.3 layout)."""
    store = FileAccountStore(data_home(env, home) / _STORE_DIRNAME)
    return UseCases(
        add=AddAccount(ClaudeLoginLauncher(), AccountDirReader(), store, SystemClock()),
        remove=RemoveAccount(store),
        list_accounts=ListAccounts(store),
        status=StatusAccount(ActiveSlotAdapter(env, home), store),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point: build the use cases from the environment, then dispatch."""
    return run(argv, build_use_cases(os.environ, Path.home()))


if __name__ == "__main__":
    sys.exit(main())
