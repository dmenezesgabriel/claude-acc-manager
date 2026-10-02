"""What the composition root injects into the transport.

``UseCases`` is the whole use-case surface ``run`` and every ``_cmd_*``
handler dispatch through — tests drive it with in-memory fakes.
``ProcessContext`` carries the two process facts (euid, container) the
root guard needs; ``__main__`` probes both.
"""

from dataclasses import dataclass
from typing import NamedTuple

from claude_acc_manager.accounts.application.ports import AccountDirPort, AccountStorePort
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
from claude_acc_manager.settings.application.ports import SettingsPort
from claude_acc_manager.settings.application.use_cases.list_settings import ListSettings
from claude_acc_manager.settings.application.use_cases.load_settings import LoadSettings
from claude_acc_manager.settings.application.use_cases.set_setting import SetSetting
from claude_acc_manager.settings.application.use_cases.unset_setting import UnsetSetting
from claude_acc_manager.usage.application.ports import ClockPort, UsageCachePort
from claude_acc_manager.usage.application.use_cases.fetch_account_usage import FetchAccountUsage


class ProcessContext(NamedTuple):
    """What the transport knows about the invoking process.

    ``euid`` feeds the root guard (docs/architecture.md §8.6): uid 0 is
    refused unless ``in_container``, where root is routine. Both fields are
    probed by the composition root — ``__main__`` reads ``os.geteuid()`` and
    ``shared.container.running_in_container``.
    """

    euid: int
    in_container: bool


@dataclass(frozen=True)
class UseCases:
    """The account and usage use cases the CLI dispatches to."""

    add: AddAccount
    remove: RemoveAccount
    list_accounts: ListAccounts
    collect_view: CollectAccountsView
    status: StatusAccount
    fetch_usage: FetchAccountUsage
    switch: SwitchAccount
    quarantine_dead_lineage: QuarantineDeadLineage
    set_enabled: SetAccountEnabled
    load_settings: LoadSettings
    set_setting: SetSetting
    unset_setting: UnsetSetting
    list_settings: ListSettings
    account_store: AccountStorePort
    account_files: AccountDirPort
    usage_cache: UsageCachePort
    usage_clock: ClockPort
    settings: SettingsPort
