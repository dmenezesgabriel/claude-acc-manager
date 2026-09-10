"""Remove an account from the store and delete its captured login dir."""

import shutil

from claude_acc_manager.accounts.application.ports import AccountStorePort
from claude_acc_manager.accounts.domain.value_objects import AccountName


class RemoveAccount:
    """Drop an account's registry entry, then delete its ``CLAUDE_CONFIG_DIR``.

    The store is updated first: it raises ``KeyError`` for an unknown account
    (and clears an active pointer aimed at it) before anything on disk is
    touched. A missing account dir is not an error — the entry is still
    removed.

    Example:
        RemoveAccount(store).execute(AccountName("work"))
    """

    def __init__(self, store: AccountStorePort) -> None:
        """Store the injected store port."""
        self._store = store

    def execute(self, name: AccountName) -> None:
        """Remove *name* from the store and delete its directory.

        Raises KeyError when the account is unknown.
        """
        self._store.remove(name)
        account_dir = self._store.account_dir(name)
        if account_dir.exists():
            shutil.rmtree(account_dir)
