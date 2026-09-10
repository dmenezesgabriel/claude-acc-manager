"""Exclusive file locking with a poll timeout.

Evidence: claude-swap locking.py FileLock (flock LOCK_EX|LOCK_NB, 0.1s poll
until timeout, error raised on timeout) — the model for guarding this tool's
own read-modify-write state files (plan §4.3 .lock).

Example:
    with exclusive_file_lock(store_root / ".lock"):
        mutate_registry_json()
"""

import fcntl
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

_POLL_INTERVAL_S = 0.1


@contextmanager
def exclusive_file_lock(path: Path, timeout_s: float = 10.0) -> Generator[None]:
    """Acquire an exclusive flock on *path*, polling until *timeout_s*.

    Raises TimeoutError when the lock is still held elsewhere after the
    deadline. The lock is released when the context exits (fd closed).

    Example:
        with exclusive_file_lock(Path("store/.lock"), timeout_s=5.0):
            registry["active"] = "work"
    """
    lock_file = path.open("w")
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.monotonic() >= deadline:
                lock_file.close()
                raise TimeoutError(
                    f"could not acquire exclusive lock {path} within {timeout_s}s"
                ) from None
            time.sleep(_POLL_INTERVAL_S)
    try:
        yield
    finally:
        lock_file.close()
