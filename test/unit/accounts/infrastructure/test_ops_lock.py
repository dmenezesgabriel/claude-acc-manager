"""Unit tests for accounts.infrastructure.ops_lock — cam's own ops lock."""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import pytest

import claude_acc_manager.accounts.infrastructure.ops_lock as ops_lock
from claude_acc_manager.accounts.application.ports import OpsLockPort
from claude_acc_manager.accounts.infrastructure.ops_lock import FlockOpsLock


class TestOpsLockAdaptsThePort:
    """FlockOpsLock explicitly subclasses the port (greppable map)."""

    def test_implements_ops_lock_port(self, tmp_path: Path) -> None:
        assert isinstance(FlockOpsLock(tmp_path), OpsLockPort)


class TestOpsLockSerializesCamOperations:
    """One store-wide flock; a second cam operation waits, then errors."""

    def test_the_lock_file_sits_at_the_store_root(self, tmp_path: Path) -> None:
        # arrange / act
        with FlockOpsLock(tmp_path).ops_locked():
            pass

        # assert — flock locks a real file; it outlives the context
        assert (tmp_path / ".ops.lock").is_file()

    def test_a_held_lock_blocks_a_second_holder(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # arrange — a live cam operation holds the store lock
        monkeypatch.setattr(ops_lock, "DEFAULT_TIMEOUT_S", 0.0)
        first = FlockOpsLock(tmp_path)
        second = FlockOpsLock(tmp_path)

        # act / assert — the second cam must refuse, not proceed unlocked
        with first.ops_locked(), pytest.raises(TimeoutError):
            with second.ops_locked():
                pass

    def test_a_released_lock_lets_the_next_holder_in(self, tmp_path: Path) -> None:
        # arrange / act / assert — close of the first fd releases the flock
        lock = FlockOpsLock(tmp_path)
        with lock.ops_locked():
            pass
        with lock.ops_locked():
            pass


class TestOpsLockTimeout:
    """The caller's bound reaches the underlying flock verbatim."""

    def test_an_explicit_timeout_is_forwarded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # arrange — capture what ops_locked hands to exclusive_file_lock
        captured: dict[str, object] = {}

        @contextmanager
        def capture(path: Path, timeout_s: float) -> Generator[None]:
            captured["path"] = path
            captured["timeout_s"] = timeout_s
            yield

        monkeypatch.setattr(ops_lock, "exclusive_file_lock", capture)

        # act
        with FlockOpsLock(tmp_path).ops_locked(timeout_s=3.5):
            pass

        # assert
        assert captured == {"path": tmp_path / ".ops.lock", "timeout_s": 3.5}

    def test_the_default_timeout_is_used_when_unspecified(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # arrange
        captured: dict[str, object] = {}

        @contextmanager
        def capture(path: Path, timeout_s: float) -> Generator[None]:
            captured["timeout_s"] = timeout_s
            yield

        monkeypatch.setattr(ops_lock, "exclusive_file_lock", capture)
        monkeypatch.setattr(ops_lock, "DEFAULT_TIMEOUT_S", 7.0)

        # act
        with FlockOpsLock(tmp_path).ops_locked():
            pass

        # assert — the module default reaches the lock, not file_lock's own
        assert captured["timeout_s"] == 7.0
