"""Adapter serializing cam's account-mutating operations via a store flock.

Claude's mkdir locks coordinate cam with claude-code; ``.ops.lock`` is cam's
own boundary — add, remove, and switch each move credentials between
account dirs and the live slot, so two cam processes must not interleave
(docs/architecture.md §3). Readers (list/status/TUI view) never take it.

Example:
    ops = FlockOpsLock(store_root)
    with ops.ops_locked():
        add.execute(AccountName("work"))
"""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from claude_acc_manager.accounts.application.ports import OpsLockPort
from claude_acc_manager.shared import fsio
from claude_acc_manager.shared.file_lock import exclusive_file_lock

_OPS_LOCK_NAME = ".ops.lock"
DEFAULT_TIMEOUT_S = 10.0


class FlockOpsLock(OpsLockPort):
    """One store-wide ``flock`` gating add / remove / switch transactions.

    Example:
        lock = FlockOpsLock(Path("~/.local/share/claude-acc-manager"))
        with lock.ops_locked():
            switch.execute(target)
    """

    def __init__(self, store_root: Path) -> None:
        """Pin the ops lock to ``<store_root>/.ops.lock``."""
        self._path = store_root / _OPS_LOCK_NAME

    @contextmanager
    def ops_locked(self, *, timeout_s: float | None = None) -> Generator[None]:
        """Hold the exclusive flock; TimeoutError when held past the bound.

        The store root is created private on first use — the ops lock can be
        the first filesystem touch inside it (e.g. a fresh ``cam add``), and
        it must not be left world-readable by a plain mkdir.
        """
        resolved = timeout_s if timeout_s is not None else DEFAULT_TIMEOUT_S
        fsio.ensure_private_dir(self._path.parent)
        with exclusive_file_lock(self._path, resolved):
            yield
