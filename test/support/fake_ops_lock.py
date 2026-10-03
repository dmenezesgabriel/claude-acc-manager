"""OpsLockPort fake recording acquisitions; can be armed to refuse."""

from collections.abc import Generator
from contextlib import contextmanager

from claude_acc_manager.accounts.application.ports import OpsLockPort


class FakeOpsLock(OpsLockPort):
    """Recording stand-in for cam's store-wide ops lock.

    ``acquired``/``released`` list "ops" in enter/exit order — pass a shared
    list to pin ordering against FakeClaudeLocks' entries. ``held`` is True
    while inside the context so a spy port can prove a mutation ran under
    the lock. ``fail`` raises TimeoutError on entry — the operation must
    not touch the store.
    """

    def __init__(self, acquired: list[str] | None = None) -> None:
        """Start unlocked; *acquired* may be a shared ordering recorder."""
        self.acquired: list[str] = acquired if acquired is not None else []
        self.released: list[str] = []
        self.held = False
        self.fail = False

    @contextmanager
    def ops_locked(self, *, timeout_s: float | None = None) -> Generator[None]:
        """Context manager recording the ops-lock acquisition."""
        if self.fail:
            raise TimeoutError("ops lock held past timeout")
        self.acquired.append("ops")
        self.held = True
        try:
            yield
        finally:
            self.held = False
            self.released.append("ops")
