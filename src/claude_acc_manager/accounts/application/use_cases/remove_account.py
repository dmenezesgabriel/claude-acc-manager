"""Remove an account from the store and delete its captured login dir."""

import shutil

from claude_acc_manager.accounts.application.ports import AccountStorePort, OpsLockPort
from claude_acc_manager.accounts.domain.value_objects import AccountName


class RemoveAccount:
    """Drop an account's registry entry, then delete its ``CLAUDE_CONFIG_DIR``.

    The store is updated first: it raises ``KeyError`` for an unknown account
    (and clears an active pointer aimed at it) before anything on disk is
    touched. A missing account dir is not an error — the entry is still
    removed. Registry drop and dir delete run under the store's ops lock so
    a concurrent add/switch cannot interleave with either step.

    Example:
        RemoveAccount(store, ops).execute(AccountName("work"))
    """

    def __init__(self, store: AccountStorePort, ops: OpsLockPort) -> None:
        """Store the injected ports."""
        self._store = store
        self._ops = ops

    def execute(self, name: AccountName) -> None:
        """Remove *name* from the store and delete its directory.

        Raises KeyError when the account is unknown.
        """
        with self._ops.ops_locked():
            self._store.remove(name)
            account_dir = self._store.account_dir(name)
            if account_dir.exists():
                shutil.rmtree(account_dir)
