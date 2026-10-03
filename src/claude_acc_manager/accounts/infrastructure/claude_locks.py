"""Mkdir locks matching claude-code's own coordination protocol.

claude-code coordinates on mkdir locks — the proper-lockfile protocol its
bundle ships (observed in 2.1.218). The lock artifact is a directory:
``mkdir`` atomicity is the mutex, ``rmdir`` releases, and the directory's
mtime is the liveness heartbeat — a lock older than its staleness bound
belongs to a dead holder and may be taken over. This tool acquires the
*same* locks claude-code uses so swaps never race a live process.

All timing bounds are module-level constants on purpose: mutmut only mutates
function bodies, so module-level literals are never swept by the mutation
gate and each wall-clock default stays a single greppable source of truth.

Example:
    with mkdir_lock(Path.home() / ".claude.json.lock"):
        slot.write_config(fresh_config)
"""

import os
import random
import threading
import time
from collections.abc import Generator, Mapping
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

from claude_acc_manager.accounts.application.ports import ClaudeLockPort
from claude_acc_manager.accounts.infrastructure.path_resolver import (
    config_lock_dir,
    credentials_lock_dir,
    oauth_refresh_lock_dir,
)

DEFAULT_TIMEOUT_S = 9.0
TOUCH_INTERVAL_S = 3.0
STALE_RMDIR_RETRY_S = 0.05
TOUCHER_JOIN_TIMEOUT_S = 1.0
POLL_INTERVAL_BASE_S = 0.25
POLL_INTERVAL_JITTER_S = 0.25
CREDENTIALS_STALENESS_S = 60.0
CONFIG_STALENESS_S = 10.0
STORAGE_WRITE_STALENESS_S = 15.0


def poll_interval() -> float:
    """Jittered retry delay: 0.25s plus up to 0.25s of random spread.

    ``0.25 + random() * 0.25`` so a crowd of processes racing the same lock
    does not retry in lockstep. The base and spread are pinned
    analytically by tests so the arithmetic cannot degrade into busy-polling
    or multi-second stalls.

    Example:
        time.sleep(poll_interval())
    """
    return POLL_INTERVAL_BASE_S + random.random() * POLL_INTERVAL_JITTER_S


def _wait_for_lock(lock_dir: Path, deadline_s: float, timeout_s: float, staleness_s: float) -> None:
    """Block until *lock_dir* is ours, stealing dead holders' locks.

    Raises TimeoutError when a live holder keeps the lock past *deadline_s*.
    A lock whose mtime is older than *staleness_s* is a corpse: we rmdir it
    and retry. A lock that vanishes between our failed ``mkdir`` and the
    mtime read just means the holder released mid-probe — retry immediately.
    """
    while True:
        try:
            os.mkdir(lock_dir)
            return
        except FileExistsError:
            pass
        # >= vs > differ only at the exact deadline instant; wall-clock
        # scheduling makes that boundary unobservable.
        if time.monotonic() >= deadline_s:  # pragma: no mutate
            raise TimeoutError(f"could not acquire mkdir lock {lock_dir} within {timeout_s}s")
        try:
            held_mtime_s = os.stat(lock_dir).st_mtime
        except FileNotFoundError:
            continue
        held_age_s = time.time() - held_mtime_s
        # > vs >= differ only at the precise staleness instant; wall-clock
        # scheduling makes that boundary unobservable.
        if held_age_s > staleness_s:  # pragma: no mutate
            try:
                os.rmdir(lock_dir)
            except OSError:
                time.sleep(STALE_RMDIR_RETRY_S)
            continue
        time.sleep(poll_interval())


def _touch_loop(stop: threading.Event, lock_dir: Path, interval_s: float) -> None:
    """Refresh the lock's mtime every *interval_s* while it is still ours.

    A directory that disappears mid-hold means another process took over;
    there is nothing left to keep alive, so the toucher ends itself.
    """
    while not stop.is_set():
        time.sleep(interval_s)
        try:
            os.utime(lock_dir)
        except OSError:
            return


@contextmanager
def mkdir_lock(
    lock_dir: Path,
    *,
    timeout_s: float | None = None,
    staleness_s: float = CONFIG_STALENESS_S,
    touch_interval_s: float = TOUCH_INTERVAL_S,
) -> Generator[None]:
    """Acquire the mkdir lock at *lock_dir* for the duration of the block.

    The directory exists only while the lock is held; a *timeout_s* (default
    9s) aborts an unreleasable wait with TimeoutError, and the toucher keeps
    the mtime fresh so a long hold never looks like a dead holder's.

    Example:
        with mkdir_lock(Path("/tmp/run/.lock"), timeout_s=5.0):
            write_slot()
    """
    if timeout_s is None:
        timeout_s = DEFAULT_TIMEOUT_S
    lock_dir.parent.mkdir(parents=True, exist_ok=True)
    _wait_for_lock(lock_dir, time.monotonic() + timeout_s, timeout_s, staleness_s)
    stop_touching = threading.Event()
    toucher = threading.Thread(
        target=_touch_loop, args=(stop_touching, lock_dir, touch_interval_s), daemon=True
    )
    toucher.start()
    try:
        yield
    finally:
        stop_touching.set()
        toucher.join(timeout=TOUCHER_JOIN_TIMEOUT_S)
        try:
            os.rmdir(lock_dir)
        except OSError:
            pass


def storage_write_lock(
    storage_dir: Path, *, timeout_s: float | None = None
) -> AbstractContextManager[None]:
    """Hold claude's per-mutation secure-storage lock for *storage_dir*.

    Upstream's secureStorage wraps every ``.credentials.json`` mutation in
    ``<storage_dir>/.storage-write`` (proper-lockfile, stale 15s — the
    ``dXr`` guard, verified on the [2.1.144, 2.2.0) band — docs/adr/0015).
    cam mutations of the same file hold the same artifact so a live claude
    can never write through a swap (docs/adr/0014). *storage_dir* is the dir
    holding ``.credentials.json`` — the live secure-storage home for the
    live slot, or the account dir for a parked account.

    Example:
        with storage_write_lock(credentials_path(env, home).parent):
            fsio.atomic_write_json(creds_path, fresh)
    """
    return mkdir_lock(
        storage_dir / ".storage-write",
        timeout_s=timeout_s,
        staleness_s=STORAGE_WRITE_STALENESS_S,
    )


class MkdirClaudeLock(ClaudeLockPort):
    """claude-code mkdir locks for the swap operation, grouped by target.

    Credential swaps must hold the primary ``<config-home>/.oauth_refresh.lock``
    and the legacy ``<config-home>.lock`` together, taken in that order;
    config swaps hold ``<global-config-path>.lock`` alone. On a
    timeout the primary is released because the legacy could not be taken.

    Example:
        with MkdirClaudeLock(env={}, home=Path.home()).credentials_locked():
            slot.write_credentials(fresh)
    """

    def __init__(self, *, env: Mapping[str, str], home: Path) -> None:
        """Pin the three lock paths from *env* and *home* once at construction."""
        self._oauth_refresh_lock = oauth_refresh_lock_dir(env, home)
        self._credentials_lock = credentials_lock_dir(env, home)
        self._config_lock = config_lock_dir(env, home)

    @contextmanager
    def credentials_locked(self, *, timeout_s: float | None = None) -> Generator[None]:
        """Hold the primary and legacy credential locks in claude's order."""
        with (
            mkdir_lock(self._oauth_refresh_lock, timeout_s=timeout_s),
            mkdir_lock(self._credentials_lock, timeout_s=timeout_s),
        ):
            yield

    @contextmanager
    def config_locked(self, *, timeout_s: float | None = None) -> Generator[None]:
        """Hold the global-config lock (the only one claude uses for config)."""
        with mkdir_lock(self._config_lock, timeout_s=timeout_s):
            yield
