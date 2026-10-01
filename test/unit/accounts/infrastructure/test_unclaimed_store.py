"""Unit tests for accounts.infrastructure.unclaimed_store and the
UnclaimedCredentialPort it implements."""

import json
import stat
from pathlib import Path

from support.fake_clock import FakeClock

from claude_acc_manager.accounts.application.ports import UnclaimedCredentialPort
from claude_acc_manager.accounts.infrastructure.unclaimed_store import FileUnclaimedStore


def _store(store_root: Path, now: str = "2026-09-10T12:00:00Z") -> FileUnclaimedStore:
    return FileUnclaimedStore(store_root, FakeClock(now))


class TestFileUnclaimedStoreAdaptsThePort:
    """FileUnclaimedStore explicitly subclasses the port (greppable map)."""

    def test_store_is_an_unclaimed_credential_port(self, tmp_path: Path):
        # arrange / act / assert
        assert isinstance(_store(tmp_path), UnclaimedCredentialPort)


class TestPreserve:
    """preserve writes a wrapped envelope under <store>/unclaimed/ at 0600."""

    def test_writes_the_envelope_and_returns_its_path(self, tmp_path: Path):
        # arrange
        creds = {"claudeAiOauth": {"accessToken": "at", "refreshToken": "rt"}}
        config = {"oauthAccount": {"emailAddress": "u@e.com"}, "numStartups": 5}

        # act
        path = _store(tmp_path).preserve(creds, config, "foreign")

        # assert
        assert path.parent == tmp_path / "unclaimed"
        assert path.name == "2026-09-10T12-00-00Z.json"
        envelope = json.loads(path.read_text(encoding="utf-8"))
        assert envelope == {
            "reason": "foreign",
            "captured_at": "2026-09-10T12:00:00Z",
            "credentials": creds,
            "config": config,
        }

    def test_no_config_is_recorded_as_null(self, tmp_path: Path):
        # arrange / act
        path = _store(tmp_path).preserve({"a": 1}, None, "unmanaged")

        # assert — a credential can outlive its config file
        assert json.loads(path.read_text(encoding="utf-8"))["config"] is None

    def test_envelope_is_0600_and_the_dir_0700(self, tmp_path: Path):
        # arrange / act
        path = _store(tmp_path).preserve({"a": 1}, None, "unmanaged")

        # assert — the stash holds a live refresh token; same privacy bar
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700

    def test_same_second_gets_a_collision_suffix(self, tmp_path: Path):
        # arrange — two preserves inside one second must not overwrite
        store = _store(tmp_path)
        first = store.preserve({"a": 1}, None, "unmanaged")

        # act
        second = store.preserve({"a": 2}, None, "foreign")

        # assert
        assert second.name == "2026-09-10T12-00-00Z.1.json"
        assert json.loads(second.read_text(encoding="utf-8"))["credentials"] == {"a": 2}
        assert json.loads(first.read_text(encoding="utf-8"))["credentials"] == {"a": 1}
