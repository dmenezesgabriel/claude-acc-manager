"""Use case for toggling an account's enabled flag."""

from dataclasses import replace

from claude_acc_manager.accounts.application.ports import AccountStorePort
from claude_acc_manager.accounts.domain.entities import Account
from claude_acc_manager.accounts.domain.value_objects import AccountName


class SetAccountEnabled:
    """Toggle whether an account participates in automatic switch picks.

    Enabled only gates *automatic* selection — rotation, next-available,
    best, and later the auto-switcher. An explicit ``cam switch <name>``
    still lands on a disabled account; the user asked for it by name.

    Example:
        set_enabled = SetAccountEnabled(store)
        account = set_enabled.execute(AccountName("work"), enabled=False)
    """

    def __init__(self, store: AccountStorePort) -> None:
        """Store the injected store port."""
        self._store = store

    def execute(self, name: AccountName, enabled: bool) -> Account:
        """Persist *enabled* on *name* and return the updated account.

        Raises KeyError when no account is registered under *name*.
        """
        account = self._store.get(name)
        if account is None:
            raise KeyError(name.value)
        self._store.set_enabled(name, enabled)
        return replace(account, enabled=enabled)
