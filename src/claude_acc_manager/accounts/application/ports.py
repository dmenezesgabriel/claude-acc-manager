"""Ports of the accounts component — the single map of every boundary."""

from typing import Protocol, runtime_checkable

from claude_acc_manager.accounts.domain.entities import Account
from claude_acc_manager.accounts.domain.value_objects import AccountName


@runtime_checkable
class AccountStorePort(Protocol):
    """Persistence boundary for registered accounts.

    Implementations guarantee private modes and atomic writes (plan §5.3).
    The registry order is the rotation order; the active pointer names the
    account whose credentials currently sit in the live slot.

    Example:
        store.upsert(account)
        store.set_active(AccountName("work"))
    """

    def upsert(self, account: Account) -> None:
        """Insert or update *account*, appending to the order if new."""
        ...

    def remove(self, name: AccountName) -> None:
        """Drop the account, its order entry, and an active pointer to it."""
        ...

    def get(self, name: AccountName) -> Account | None:
        """Return the account or None when unknown."""
        ...

    def list_accounts(self) -> list[Account]:
        """All accounts in registry order."""
        ...

    def set_enabled(self, name: AccountName, enabled: bool) -> None:
        """Toggle the account's enabled flag."""
        ...

    def set_active(self, name: AccountName | None) -> None:
        """Point the registry's active pointer at *name* (or unset it)."""
        ...

    def active(self) -> Account | None:
        """The active account, or None when unset or dangling."""
        ...
