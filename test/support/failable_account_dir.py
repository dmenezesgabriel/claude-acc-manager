"""FakeAccountDir that records mutations and can be armed to fail one.

Rollback tests arm a single operation — e.g. ``delete_credentials`` on the
target's dir — to raise mid-transaction, then assert every prior mutation
was restored.
"""

from pathlib import Path

from support.fake_account_dir import FakeAccountDir


class FailableAccountDir(FakeAccountDir):
    """FakeAccountDir with per-operation failure injection."""

    def __init__(self) -> None:
        """Start empty and unarmed."""
        super().__init__()
        self.calls: list[tuple[str, Path]] = []
        self._armed: dict[str, Exception] = {}
        self._pinned: dict[str, Exception] = {}

    def arm(self, op: str, error: Exception) -> None:
        """The next call to *op* is recorded, then raises *error*."""
        self._armed[op] = error

    def pin(self, op: str, error: Exception) -> None:
        """Every call to *op* raises *error* — including a rollback restore."""
        self._pinned[op] = error

    def _attempt(self, op: str, account_dir: Path) -> None:
        """Record the attempted call, then raise when armed or pinned."""
        self.calls.append((op, account_dir))
        if op in self._armed:
            raise self._armed.pop(op)
        if op in self._pinned:
            raise self._pinned[op]

    def write_credentials(self, account_dir: Path, credentials: dict[str, object]) -> None:
        """Record, maybe raise, else delegate."""
        self._attempt("write_credentials", account_dir)
        super().write_credentials(account_dir, credentials)

    def delete_credentials(self, account_dir: Path) -> None:
        """Record, maybe raise, else delegate."""
        self._attempt("delete_credentials", account_dir)
        super().delete_credentials(account_dir)

    def write_config(self, account_dir: Path, config: dict[str, object]) -> None:
        """Record, maybe raise, else delegate."""
        self._attempt("write_config", account_dir)
        super().write_config(account_dir, config)

    def delete_config(self, account_dir: Path) -> None:
        """Record, maybe raise, else delegate."""
        self._attempt("delete_config", account_dir)
        super().delete_config(account_dir)
