"""In-memory UpdateCheckCachePort fake for hermetic use-case tests."""

from claude_acc_manager.update.application.ports import (
    UpdateCheckCachePort,
    UpdateCheckRecord,
)


class InMemoryUpdateCheckCache(UpdateCheckCachePort):
    """UpdateCheckCachePort backed by a single in-memory slot.

    ``saves`` keeps every saved record in order so tests can assert a
    failure was cached — or that a fresh cache meant nothing was written.
    """

    def __init__(self, record: UpdateCheckRecord | None = None) -> None:
        """Start empty, or pre-seeded with *record*."""
        self._record = record
        self.saves: list[UpdateCheckRecord] = []

    def load(self) -> UpdateCheckRecord | None:
        """The seeded or saved record, or None when nothing was ever stored."""
        return self._record

    def save(self, record: UpdateCheckRecord) -> None:
        """Replace the stored record and record the save."""
        self._record = record
        self.saves.append(record)
