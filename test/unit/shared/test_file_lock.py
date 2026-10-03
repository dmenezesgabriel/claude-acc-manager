"""Unit tests for shared.file_lock — exclusive flock with poll timeout."""

import errno
import fcntl
import threading
import time
from pathlib import Path

import pytest

from claude_acc_manager.shared.file_lock import exclusive_file_lock


class TestExclusiveFileLock:
    """flock(LOCK_EX|LOCK_NB) polled every 0.1s until timeout, then raised."""

    def test_lock_is_taken_and_released(self, tmp_path: Path):
        # arrange
        lock_path = tmp_path / ".lock"

        # act
        with exclusive_file_lock(lock_path):
            # assert — we hold it: a sibling flock on a fresh fd fails
            probe = lock_path.open("w")
            try:
                with pytest.raises(OSError) as raised:
                    fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                assert raised.value.errno == errno.EWOULDBLOCK
            finally:
                probe.close()

        # after release, re-acquiring on a fresh fd succeeds
        probe = lock_path.open("w")
        try:
            fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(probe.fileno(), fcntl.LOCK_UN)
        finally:
            probe.close()

    def test_times_out_while_a_sibling_holds_it(self, tmp_path: Path):
        # arrange — hold the lock from a sibling thread beyond the timeout
        lock_path = tmp_path / ".lock"
        held = threading.Event()

        def hold() -> None:
            with exclusive_file_lock(lock_path):
                held.set()
                time.sleep(1.0)

        thread = threading.Thread(target=hold)
        thread.start()
        held.wait()

        # act / assert
        try:
            with pytest.raises(TimeoutError):
                with exclusive_file_lock(lock_path, timeout_s=0.2):
                    pass
        finally:
            thread.join()

    def test_acquires_once_the_sibling_releases(self, tmp_path: Path):
        # arrange — main waits for the sibling to demonstrably hold the lock,
        # then contends; flock semantics guarantee we can only hold it after
        # the sibling's close()
        lock_path = tmp_path / ".lock"
        sibling_has_lock = threading.Event()
        sibling_releasing = threading.Event()

        def hold_then_release() -> None:
            with exclusive_file_lock(lock_path):
                sibling_has_lock.set()
                time.sleep(0.1)
                sibling_releasing.set()

        thread = threading.Thread(target=hold_then_release)

        # act
        thread.start()
        try:
            assert sibling_has_lock.wait(timeout=2)
            with exclusive_file_lock(lock_path, timeout_s=2.0):
                # assert — we hold it, so the sibling's fd is closed
                assert sibling_releasing.is_set()
        finally:
            thread.join()

    def test_serializes_two_threads(self, tmp_path: Path):
        # arrange — the writer only contends after the holder demonstrably
        # holds the lock, and asserts it exited first; the event sequence
        # proves the exclusive regions never interleaved
        lock_path = tmp_path / ".lock"
        events: list[str] = []
        holder_has_lock = threading.Event()
        holder_done = threading.Event()

        def holder() -> None:
            with exclusive_file_lock(lock_path):
                events.append("holder:enter")
                holder_has_lock.set()
                time.sleep(0.1)
                holder_done.set()
                # recorded inside the region: the writer can only acquire
                # after our fd closes, i.e. after this append
                events.append("holder:exit")

        def writer() -> None:
            holder_has_lock.wait(timeout=2)
            with exclusive_file_lock(lock_path):
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
