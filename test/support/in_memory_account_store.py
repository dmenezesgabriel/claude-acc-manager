"""In-memory AccountStorePort fake for hermetic use-case tests.

Honors the port contract exactly (plan §7 names this fake): ``remove`` and
``set_enabled`` raise ``KeyError`` for an unknown account, ``remove`` drops an
active pointer aimed at the removed account, and ``active`` returns ``None``
for an unset or dangling pointer — the same guarantees ``FileAccountStore``
gives, so a use-case test exercising this fake proves the same behavior.
"""

from dataclasses import replace
from pathlib import Path

from claude_acc_manager.accounts.application.ports import AccountStorePort
from claude_acc_manager.accounts.domain.entities import Account
from claude_acc_manager.accounts.domain.value_objects import AccountName


class InMemoryAccountStore(AccountStorePort):
    """AccountStorePort backed by dicts; *store_root* seeds ``account_dir``."""

    def __init__(self, store_root: Path) -> None:
        """Keep accounts keyed by name, plus insertion order and the active name."""
        self._store_root = store_root
        self._accounts: dict[str, Account] = {}
        self._order: list[str] = []
        self._active: str | None = None

    def upsert(self, account: Account) -> None:
        """Insert or replace, appending to the order only when new."""
        if account.name.value not in self._accounts:
            self._order.append(account.name.value)
        self._accounts[account.name.value] = account

    def remove(self, name: AccountName) -> None:
        """Drop the record, its order entry, and an active pointer to it."""
        if name.value not in self._accounts:
            raise KeyError(name.value)
        del self._accounts[name.value]
        self._order.remove(name.value)
        if self._active == name.value:
            self._active = None

    def get(self, name: AccountName) -> Account | None:
        """The account, or ``None`` when unknown."""
        return self._accounts.get(name.value)

    def list_accounts(self) -> list[Account]:
        """All accounts in registry order."""
        return [self._accounts[name] for name in self._order]

    def set_enabled(self, name: AccountName, enabled: bool) -> None:
        """Persist the enabled flag; ``KeyError`` when unknown."""
        if name.value not in self._accounts:
            raise KeyError(name.value)
        self._accounts[name.value] = replace(self._accounts[name.value], enabled=enabled)

    def set_active(self, name: AccountName | None) -> None:
        """Point the active pointer at *name*, or unset with ``None``."""
        self._active = name.value if name else None

    def active(self) -> Account | None:
        """The active account; ``None`` when unset or dangling."""
        if self._active is None:
            return None
        return self._accounts.get(self._active)

    def account_dir(self, name: AccountName) -> Path:
        """``<store_root>/accounts/<name>`` — the store owns the layout."""
        return self._store_root / "accounts" / name.value
