"""Unit tests for accounts.infrastructure.claude_locks.

The lock protocol (the proper-lockfile protocol claude-code 2.1.218
bundles): the artifact is a directory; ``mkdir`` atomicity is the mutex;
mtime is the liveness heartbeat; a lock older than its staleness bound is a
dead holder's and may be taken over. We touch faster than Claude Code (3s
vs its 5s) for margin.
"""

import os
import threading
import time
from pathlib import Path

import pytest

import claude_acc_manager.accounts.infrastructure.claude_locks as claude_locks
from claude_acc_manager.accounts.infrastructure.claude_locks import (
    CONFIG_STALENESS_S,
    CREDENTIALS_STALENESS_S,
    MkdirClaudeLock,
    mkdir_lock,
    poll_interval,
)
from claude_acc_manager.accounts.infrastructure.path_resolver import (
    config_lock_dir,
    credentials_lock_dir,
    oauth_refresh_lock_dir,
)

EMPTY_ENV: dict[str, str] = {}


class TestMkdirLock:
    """mkdir is the mutex; mtime is the heartbeat; stale locks are stealable."""

    def test_lock_dir_created_while_held_removed_on_exit(self, tmp_path: Path):
        # arrange
        lock_dir = tmp_path / ".lock"

        # act
        with mkdir_lock(lock_dir):
            # assert — the directory exists exactly while the lock is held
            assert lock_dir.is_dir()
        # after release the lock artifact is gone
        assert not lock_dir.exists()

    def test_parent_directories_are_created(self, tmp_path: Path):
        # arrange — a lock whose parent does not exist yet
        lock_dir = tmp_path / "nested" / ".lock"

        # act
        with mkdir_lock(lock_dir):
            # assert — mkdir happened, so the parent must exist
            assert lock_dir.is_dir()

        # assert — exit removed only the lock, not the parent
        assert (tmp_path / "nested").is_dir()

    def test_acquires_when_uncontended_after_first_waiter(self, tmp_path: Path):
        # arrange
        lock_dir = tmp_path / ".lock"
        first_wait = threading.Event()

        def hold_briefly() -> None:
            with mkdir_lock(lock_dir, timeout_s=5.0):
                first_wait.set()
                time.sleep(0.1)

        thread = threading.Thread(target=hold_briefly)

        # act — the second locker waits for the first to release
        thread.start()
        try:
            first_wait.wait(timeout=2)
            with mkdir_lock(lock_dir, timeout_s=2.0):
                assert lock_dir.is_dir()
        finally:
            thread.join()

    def test_times_out_while_sibling_holds_it(self, tmp_path: Path):
        # arrange — hold the lock from a sibling thread beyond the deadline
        lock_dir = tmp_path / ".lock"
        held = threading.Event()

        def hold() -> None:
            with mkdir_lock(lock_dir, timeout_s=5.0):
                held.set()
                time.sleep(1.0)

        thread = threading.Thread(target=hold)

        # act / assert
        thread.start()
        try:
            assert held.wait(timeout=2)
            with pytest.raises(TimeoutError) as raised:
                with mkdir_lock(lock_dir, timeout_s=0.2):
                    pass
            # assert — the error names the lock we failed to acquire (AGENTS)
            assert str(raised.value) == f"could not acquire mkdir lock {lock_dir} within 0.2s"
        finally:
            thread.join()

    def test_steals_a_stale_lock(self, tmp_path: Path):
        # arrange — a dead holder's lock, older than the staleness bound
        lock_dir = tmp_path / ".lock"
        lock_dir.mkdir()
        ancient = time.time() - 200.0
        os.utime(lock_dir, (ancient, ancient))

        # act
        with mkdir_lock(lock_dir, staleness_s=10.0):
            # assert — we took over the dead holder's lock
            assert lock_dir.is_dir()
        assert not lock_dir.exists()

    def test_does_not_steal_a_fresh_lock(self, tmp_path: Path):
        # arrange — a live lock is younger than the staleness bound
        lock_dir = tmp_path / ".lock"
        lock_dir.mkdir()

        # act / assert — a fresh lock must never be stolen; we wait instead
        with pytest.raises(TimeoutError):
            with mkdir_lock(lock_dir, timeout_s=0.2, staleness_s=10.0):
                pass

    def test_vanish_between_mkdir_and_stat_retries(self, tmp_path: Path, monkeypatch):
        # arrange — the recorded holder released between our failed mkdir and our
        # stat, so the lock is already gone when we try to read its mtime;
        # only the lock dir itself counts — parent.mkdir probes it first
        # via os.mkdir
        lock_dir = tmp_path / ".lock"
        real_mkdir = os.mkdir
        mkdir_calls = 0

        def mkdir_first_attempt_sees_foreign_lock(
            path: str | bytes | os.PathLike[str], mode: int = 0o777
        ):
            # only the first attempt on the lock itself simulates a live holder
            nonlocal mkdir_calls
            if path == lock_dir:
                mkdir_calls += 1
                if mkdir_calls == 1:
                    raise FileExistsError("foreign lock here")
            return real_mkdir(path, mode)

        monkeypatch.setattr(os, "mkdir", mkdir_first_attempt_sees_foreign_lock)

        # act — the field empties; we retry and acquire
        with mkdir_lock(lock_dir, timeout_s=1.0, staleness_s=10.0):
            assert lock_dir.is_dir()
        # assert — the first attempt saw the foreign lock, the second created ours
        assert mkdir_calls == 2

    def test_stale_steal_retries_when_rmdir_fails(self, tmp_path: Path, monkeypatch):
        # arrange — a rival stole the dead lock between our stat and rmdir, so
        # the rmdir fails once; we must retry instead of abandoning the steal
        lock_dir = tmp_path / ".lock"
        lock_dir.mkdir()
        ancient = time.time() - 200.0
        os.utime(lock_dir, (ancient, ancient))
        real_rmdir = os.rmdir
        rmdir_calls = 0

        def rmdir_fails_once(directory: str | bytes | os.PathLike[str], dir_fd: int | None = None):
            nonlocal rmdir_calls
            rmdir_calls += 1
            if rmdir_calls == 1:
                raise OSError("transient rmdir failure")
            return real_rmdir(directory)

        monkeypatch.setattr(os, "rmdir", rmdir_fails_once)

        # act — the stale lock is still stealable despite the balky rmdir
        with mkdir_lock(lock_dir, staleness_s=10.0):
            assert lock_dir.is_dir()
        assert not lock_dir.exists()

    def test_takeover_while_holding_never_blocks_exit(self, tmp_path: Path):
        # arrange — claude-code can steal our lock mid-session; the toucher then
        # finds nothing to refresh and the exit path must not choke on the miss
        lock_dir = tmp_path / ".lock"

        # act — steal our own lock (simulating a takeover) then release
        with mkdir_lock(lock_dir, touch_interval_s=0.02):
            os.rmdir(lock_dir)
            time.sleep(0.05)
        # assert — the stale toucher died quietly and release succeeded

    def test_toucher_keeps_lock_fresh_while_held(self, tmp_path: Path):
        # arrange — a lock is only safe to steal if it stopped being touched;
        # the toucher must refresh the mtime while the lock is held
        lock_dir = tmp_path / ".lock"
        with mkdir_lock(lock_dir, touch_interval_s=0.02):
            time.sleep(0.09)
            fresh = os.stat(lock_dir).st_mtime
            # assert — much newer than the touch interval, i.e. the holder touched it
            assert time.time() - fresh < 0.05

    def test_serializes_two_threads(self, tmp_path: Path):
        # arrange — the writer only contends after the holder demonstrably
        # holds, then asserts the holder exited first; the event sequence
        # proves the exclusive regions never interleaved
        lock_dir = tmp_path / ".lock"
        events: list[str] = []
        holder_has_lock = threading.Event()
        holder_done = threading.Event()

        def holder() -> None:
            with mkdir_lock(lock_dir, timeout_s=5.0):
                events.append("holder:enter")
                holder_has_lock.set()
                time.sleep(0.1)
                holder_done.set()
                events.append("holder:exit")

        def writer() -> None:
            holder_has_lock.wait(timeout=2)
            with mkdir_lock(lock_dir, timeout_s=3.0):
                events.append("second:enter")
                assert holder_done.is_set()
                events.append("second:exit")

        # act
        threads = [threading.Thread(target=holder), threading.Thread(target=writer)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # assert
        assert events == ["holder:enter", "holder:exit", "second:enter", "second:exit"]


class TestStalenessConstants:
    """The staleness bounds encode claude-code's own thresholds (2.1.218)."""

    def test_credentials_staleness_is_60_seconds(self):
        # arrange
        # act / assert — a credential refresh can legitimately hold 60s
        assert CREDENTIALS_STALENESS_S == 60.0

    def test_config_staleness_is_10_seconds(self):
        # arrange
        # act / assert — the config lock keeps proper-lockfile's older defaults
        assert CONFIG_STALENESS_S == 10.0


class TestPollInterval:
    """poll_interval is the resource-freeing retry cadence
    (0.25 + random() * 0.25), pinned analytically so the arithmetic cannot
    silently degrade into busy-polling or long sleeping."""

    def test_returns_base_when_random_is_zero(self, monkeypatch):
        # arrange
        monkeypatch.setattr(claude_locks.random, "random", lambda: 0.0)

        # act / assert
        assert poll_interval() == 0.25

    def test_returns_top_when_random_is_one(self, monkeypatch):
        # arrange
        monkeypatch.setattr(claude_locks.random, "random", lambda: 1.0)

        # act / assert
        assert poll_interval() == 0.5


class TestLockDirHelpers:
    """The three lock locations mirror claude-code's mkdir layout."""

    def test_default_layout_matches_claude_code(self, tmp_path: Path):
        # arrange
        home = tmp_path / "home"
        config_home = home / ".claude"

        # act
        oauth = oauth_refresh_lock_dir(EMPTY_ENV, home)
        legacy = credentials_lock_dir(EMPTY_ENV, home)
        config = config_lock_dir(EMPTY_ENV, home)

        # assert — <config-home>/.oauth_refresh.lock, ~/.claude.lock, ~/.claude.json.lock
        assert oauth == config_home / ".oauth_refresh.lock"
        assert legacy == home / ".claude.lock"
        assert config == home / ".claude.json.lock"

    def test_claude_config_dir_shapes_all_locks(self, tmp_path: Path):
        # arrange
        profile = tmp_path / "profile"
        env = {"CLAUDE_CONFIG_DIR": str(profile)}
        home = tmp_path / "home"

        # act
        oauth = oauth_refresh_lock_dir(env, home)
        legacy = credentials_lock_dir(env, home)
        config = config_lock_dir(env, home)

        # assert — the override moves primary and legacy locks next to itself
        assert oauth == profile / ".oauth_refresh.lock"
        assert legacy == tmp_path / "profile.lock"
        assert config == profile / ".claude.json.lock"

    def test_legacy_config_lock_follows_legacy_config_file(self, tmp_path: Path):
        # arrange — a legacy <config-home>/.config.json reroutes the config lock
        profile = tmp_path / "profile"
        profile.mkdir()
        (profile / ".config.json").write_text("{}", encoding="utf-8")
        env = {"CLAUDE_CONFIG_DIR": str(profile)}

        # act
        config = config_lock_dir(env, tmp_path / "home")

        # assert — the lock guards the file claude actually reads
        assert config == profile / ".config.json.lock"


class TestMkdirClaudeLock:
    """Adapter wiring: credentials pair + config lock at the right locations."""

    def make_adapter(self, tmp_path: Path) -> tuple[MkdirClaudeLock, Path, Path]:
        home = tmp_path / "home"
        return (
            MkdirClaudeLock(env=EMPTY_ENV, home=home),
            home,
            tmp_path / "home",
        )

    def test_credentials_lock_creates_both_artifacts(self, tmp_path: Path):
        # arrange
        adapter, home, _ = self.make_adapter(tmp_path)
        oauth = oauth_refresh_lock_dir(EMPTY_ENV, home)
        legacy = credentials_lock_dir(EMPTY_ENV, home)

        # act — hold the credential pair
        with adapter.credentials_locked(timeout_s=2.0):
            # assert — CC's primary and legacy locks exist (interop shape)
            assert oauth.is_dir()
            assert legacy.is_dir()

        # assert — both released on exit
        assert not oauth.exists()
        assert not legacy.exists()

    def test_credentials_lock_times_out_when_path_lock_held(self, tmp_path: Path):
        # arrange — a live external holder owns the legacy lock
        adapter, home, _ = self.make_adapter(tmp_path)
        legacy = credentials_lock_dir(EMPTY_ENV, home)
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.mkdir()

        # act / assert — the composite must not steal a fresh legacy lock
        with pytest.raises(TimeoutError) as raised:
            with adapter.credentials_locked(timeout_s=0.2):
                pass
        # assert — the timeout names the legacy lock we could not take
        assert str(raised.value) == f"could not acquire mkdir lock {legacy} within 0.2s"
        # assert — the external holder's artifact is untouched
        assert legacy.is_dir()
        assert not oauth_refresh_lock_dir(EMPTY_ENV, home).exists()

    def test_config_lock_guards_config_path(self, tmp_path: Path):
        # arrange
        adapter, home, _ = self.make_adapter(tmp_path)
        config = config_lock_dir(EMPTY_ENV, home)

        # act
        with adapter.config_locked(timeout_s=2.0):
            # assert — only the config lock is held, not the credential pair
            assert config.is_dir()
            assert not oauth_refresh_lock_dir(EMPTY_ENV, home).exists()
            assert not credentials_lock_dir(EMPTY_ENV, home).exists()

        # assert — released
        assert not config.exists()
