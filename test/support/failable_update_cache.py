"""InMemoryUpdateCheckCache that can be pinned to fail — never-raises tests.

``CheckUpdate`` promises the release check can never break the command that
triggered it, so the cache it sits on needs load/save failure injection —
the same discipline FailableAccountStore brings to rollback tests.
"""

from claude_acc_manager.update.application.ports import UpdateCheckRecord
from support.in_memory_update_cache import InMemoryUpdateCheckCache


class FailableUpdateCheckCache(InMemoryUpdateCheckCache):
    """InMemoryUpdateCheckCache with per-operation failure injection."""

    def __init__(self, record: UpdateCheckRecord | None = None) -> None:
        """Seed like the base fake; start unarmed."""
        super().__init__(record)
        self.calls: list[str] = []
        self._pinned: dict[str, Exception] = {}

    def pin(self, op: str, error: Exception) -> None:
        """Every call to *op* is recorded, then raises *error*."""
        self._pinned[op] = error

    def _attempt(self, op: str) -> None:
        """Record the attempted call, then raise when pinned."""
        self.calls.append(op)
        if op in self._pinned:
            raise self._pinned[op]

    def load(self) -> UpdateCheckRecord | None:
        """Record, maybe raise, else delegate."""
        self._attempt("load")
        return super().load()

    def save(self, record: UpdateCheckRecord) -> None:
        """Record, maybe raise, else delegate."""
        self._attempt("save")
        super().save(record)
