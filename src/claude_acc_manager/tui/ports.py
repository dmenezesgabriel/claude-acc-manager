"""The use-case surface the TUI consumes — satisfied by cli ``UseCases``.

Declared structurally so the TUI never imports the other transport (the
import-linter `tui` contract forbids ``claude_acc_manager.cli``). The
attributes are properties — read-only — so the frozen ``UseCases``
dataclass satisfies the protocol without loosening its immutability.
"""

from __future__ import annotations

from typing import Protocol

from claude_acc_manager.accounts.application.use_cases.collect_accounts_view import (
    CollectAccountsView,
)
from claude_acc_manager.accounts.application.use_cases.quarantine_dead_lineage import (
    QuarantineDeadLineage,
)
from claude_acc_manager.accounts.application.use_cases.remove_account import RemoveAccount
from claude_acc_manager.accounts.application.use_cases.set_account_enabled import (
    SetAccountEnabled,
)
from claude_acc_manager.accounts.application.use_cases.switch_account import SwitchAccount
from claude_acc_manager.settings.application.use_cases.list_settings import ListSettings
from claude_acc_manager.settings.application.use_cases.load_privacy_settings import (
    LoadPrivacySettings,
)
from claude_acc_manager.settings.application.use_cases.load_settings import LoadSettings
from claude_acc_manager.settings.application.use_cases.set_setting import SetSetting
from claude_acc_manager.update.application.use_cases.check_update import CheckUpdate
from claude_acc_manager.usage.application.ports import ClockPort
from claude_acc_manager.usage.application.use_cases.fetch_account_usage import (
    FetchAccountUsage,
)


class TuiUseCases(Protocol):
    """The use-case surface the TUI consumes — satisfied by cli ``UseCases``.

    Declared structurally so the TUI never imports the other transport (the
    import-linter `tui` contract forbids ``claude_acc_manager.cli``). The
    attributes are properties — read-only — so the frozen ``UseCases``
    dataclass satisfies the protocol without loosening its immutability.
    """

    @property
    def collect_view(self) -> CollectAccountsView:
        """The one-pass dashboard read model."""
        ...

    @property
    def fetch_usage(self) -> FetchAccountUsage:
        """The gated per-account usage fetch."""
        ...

    @property
    def quarantine_dead_lineage(self) -> QuarantineDeadLineage:
        """Tombstones a refresh-token lineage the provider rejected."""
        ...

    @property
    def set_enabled(self) -> SetAccountEnabled:
        """Flips an account's participation in automatic picks."""
        ...

    @property
    def remove(self) -> RemoveAccount:
        """Drops a registry entry and deletes its stored login dir."""
        ...

    @property
    def switch(self) -> SwitchAccount:
        """Moves the live login to another account, transactionally."""
        ...

    @property
    def usage_clock(self) -> ClockPort:
        """The clock the view stamps ``taken_at_s`` with."""
        ...

    @property
    def list_settings(self) -> ListSettings:
        """One ``EffectiveSetting`` row per spec key, in spec order."""
        ...

    @property
    def load_settings(self) -> LoadSettings:
        """The forgiving section read — clamped effective ``AutoSettings``."""
        ...

    @property
    def load_privacy_settings(self) -> LoadPrivacySettings:
        """The forgiving read — clamped effective ``PrivacySettings``."""
        ...

    @property
    def set_setting(self) -> SetSetting:
        """Strict-validate one ``dotted.key`` string, then persist it."""
        ...

    @property
    def check_update(self) -> CheckUpdate:
        """The cached release probe — the mount-time toast asks it once."""
        ...
