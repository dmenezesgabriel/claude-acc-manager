"""FileAutoState — auto-state.json (schema v1) under its dedicated lock."""

import json
import os
import stat
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from claude_acc_manager.auto.domain.auto_state import EMPTY_AUTO_STATE, AutoState
from claude_acc_manager.auto.infrastructure.file_auto_state import FileAutoState


class TestLoad:
    def test_missing_file_loads_empty(self, tmp_path: Path):
        # act/assert
        assert FileAutoState(tmp_path).load() == EMPTY_AUTO_STATE

    def test_round_trip(self, tmp_path: Path):
        # arrange
        state = AutoState(
            last_switch_at_s=1700000000.0,
            last_switch_from="work",
            last_switch_to="personal",
            left_headroom=12.5,
            left_recovery_at_s=1700003600.0,
        )
        adapter = FileAutoState(tmp_path)

        # act
        with adapter.locked():
            adapter.save(state)

        # assert — value and the exact persisted document
        assert adapter.load() == state
        assert json.loads((tmp_path / "auto-state.json").read_text()) == {
            "schemaVersion": 1,
            "lastSwitchAt": 1700000000.0,
            "lastSwitchFrom": "work",
            "lastSwitchTo": "personal",
            "leftHeadroom": 12.5,
            "leftRecoveryAt": 1700003600.0,
        }

    def test_null_fields_round_trip(self, tmp_path: Path):
        # arrange — a switch whose left account had no measurable recovery
        state = AutoState(last_switch_at_s=5.0, last_switch_from="a")
        adapter = FileAutoState(tmp_path)

        # act
        with adapter.locked():
            adapter.save(state)

        # assert
        assert adapter.load() == state
        raw = json.loads((tmp_path / "auto-state.json").read_text())
        assert raw["leftRecoveryAt"] is None

    def test_torn_file_raises(self, tmp_path: Path):
        # arrange — machine-written state is strict: a tear is never "empty"
        (tmp_path / "auto-state.json").write_bytes(b"{not json")

        # act/assert
        with pytest.raises(ValueError, match=r"auto-state file .*torn"):
            FileAutoState(tmp_path).load()

    def test_non_object_file_raises(self, tmp_path: Path):
        # arrange
        (tmp_path / "auto-state.json").write_text("[1, 2]")

        # act/assert
        with pytest.raises(ValueError, match=r"auto-state file .*list, not a JSON object"):
            FileAutoState(tmp_path).load()


class TestPathsAndModes:
    def test_files_land_under_the_store_root(self, tmp_path: Path):
        # arrange
        adapter = FileAutoState(tmp_path)

        # act
        with adapter.locked():
            adapter.save(AutoState(last_switch_at_s=1.0))

        # assert — the state file, its dedicated lock, and the mode
        assert (tmp_path / "auto-state.json").is_file()
        assert (tmp_path / ".auto-state.lock").exists()
        mode = stat.S_IMODE(os.stat(tmp_path / "auto-state.json").st_mode)
        assert mode == 0o600

    def test_dedicated_lock_not_the_store_lock(self, tmp_path: Path):
        # arrange/act
        with FileAutoState(tmp_path).locked():
            pass

        # assert — never the shared .lock (it would self-deadlock the switch)
        assert (tmp_path / ".auto-state.lock").exists()
        assert not (tmp_path / ".lock").exists()


class TestLocked:
    def test_save_inside_locked_persists(self, tmp_path: Path):
        # arrange
        adapter = FileAutoState(tmp_path)

        # act
        with adapter.locked():
            adapter.save(replace(EMPTY_AUTO_STATE, last_switch_from="work"))

        # assert
        assert adapter.load().last_switch_from == "work"

    def test_locked_serializes_competing_writers(self, tmp_path: Path):
        # arrange — two threads mutate under the lock; both writes land
        adapter = FileAutoState(tmp_path)
        done: list[str] = []

        def write(from_name: str) -> None:
            with adapter.locked():
                state = adapter.load()
                time.sleep(0.01)
                adapter.save(replace(state, last_switch_from=from_name))
            done.append(from_name)

        threads = [threading.Thread(target=write, args=(n,)) for n in ("a", "b")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # assert — one writer won; the winner's value is all of it (no tear)
        assert sorted(done) == ["a", "b"]
        assert adapter.load().last_switch_from in {"a", "b"}
