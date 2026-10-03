"""ClaudeLockPort fake recording acquisitions; can be armed to refuse."""

from collections.abc import Iterator
from contextlib import contextmanager

from claude_acc_manager.accounts.application.ports import ClaudeLockPort


class FakeClaudeLocks(ClaudeLockPort):
    """Recording stand-in for claude-code's mkdir locks.

    ``acquired`` lists locks in enter order; ``released`` in exit order —
    the pair pins both that a mutation ran under both locks and that the
    scope closed. ``fail`` holds lock names whose acquisition raises
    ``TimeoutError`` — the switch must not touch the slot.
    """

    def __init__(self, acquired: list[str] | None = None) -> None:
        """Start unlocked; *acquired* may be a shared ordering recorder."""
        self.acquired: list[str] = acquired if acquired is not None else []
        self.released: list[str] = []
        self.fail: set[str] = set()

    def credentials_locked(self, *, timeout_s: float | None = None):
        """Context manager recording the credential-lock acquisition."""
        return self._guard("credentials")

    def config_locked(self, *, timeout_s: float | None = None):
        """Context manager recording the config-lock acquisition."""
        return self._guard("config")

    @contextmanager
    def _guard(self, name: str) -> Iterator[None]:
        """Enter/exit bookkeeping; TimeoutError when armed."""
        if name in self.fail:
            raise TimeoutError(f"{name} lock held past timeout")
        self.acquired.append(name)
        try:
            yield
        finally:
            self.released.append(name)
