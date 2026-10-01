"""InMemoryAccountStore that can be armed to fail one mutation — rollback tests."""

from pathlib import Path

from claude_acc_manager.accounts.domain.value_objects import AccountName
from support.in_memory_account_store import InMemoryAccountStore


class FailableAccountStore(InMemoryAccountStore):
    """InMemoryAccountStore with per-operation failure injection."""

    def __init__(self, store_root: Path) -> None:
        """Start empty and unarmed."""
        super().__init__(store_root)
        self.calls: list[str] = []
        self._armed: dict[str, Exception] = {}
        self._pinned: dict[str, Exception] = {}

    def arm(self, op: str, error: Exception) -> None:
        """The next call to *op* is recorded, then raises *error*."""
        self._armed[op] = error

    def pin(self, op: str, error: Exception) -> None:
        """Every call to *op* raises *error* — including a rollback restore."""
        self._pinned[op] = error

    def _attempt(self, op: str) -> None:
        """Record the attempted call, then raise when armed or pinned."""
        self.calls.append(op)
        if op in self._armed:
            raise self._armed.pop(op)
        if op in self._pinned:
            raise self._pinned[op]

    def set_active(self, name: AccountName | None) -> None:
        """Record, maybe raise, else delegate."""
        self._attempt("set_active")
        super().set_active(name)
