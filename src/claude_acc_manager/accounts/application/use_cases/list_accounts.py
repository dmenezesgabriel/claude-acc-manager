"""Use case for listing all managed accounts."""

from typing import NamedTuple

from claude_acc_manager.accounts.application.ports import AccountStorePort
from claude_acc_manager.accounts.domain.entities import Account


class AccountSummary(NamedTuple):
    """Summary of an account for listing."""

    account: Account
    is_active: bool


class ListAccounts:
    """List all managed accounts in registry order.

    Returns accounts with an active marker for the currently active account.

    Example:
        list_accounts = ListAccounts(store)
        summaries = list_accounts.execute()
    """

    def __init__(self, store: AccountStorePort) -> None:
        """Store the injected store port."""
        self._store = store

    def execute(self) -> list[AccountSummary]:
        """Return all accounts with active markers in registry order."""
        accounts = self._store.list_accounts()
        active = self._store.active()
        active_name = active.name.value if active else None

        return [
            AccountSummary(account=account, is_active=account.name.value == active_name)
            for account in accounts
        ]
