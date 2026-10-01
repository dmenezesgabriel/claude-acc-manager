"""ListAccounts that raises KeyboardInterrupt — Ctrl-C landing mid-list."""

from claude_acc_manager.accounts.application.use_cases.list_accounts import (
    AccountSummary,
    ListAccounts,
)


class InterruptingListAccounts(ListAccounts):
    """Simulates Ctrl-C inside a use case on a command with no --json flag."""

    def __init__(self) -> None:
        """Execute raises before it can read the store — inject nothing."""

    def execute(self) -> list[AccountSummary]:
        """Raise KeyboardInterrupt unconditionally."""
        raise KeyboardInterrupt
