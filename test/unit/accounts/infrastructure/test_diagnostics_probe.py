"""Unit tests for accounts.infrastructure.diagnostics_probe.

The adapter resolves the same paths and locks the swap path uses
(path_resolver, claude_locks staleness bounds) — hermetic because env,
home, store_root, and the contract probe are injected.
"""

import os
import sys
import time
from pathlib import Path

import pytest
from support.fake_claude_contract import FakeClaudeContractProbe

from claude_acc_manager.accounts.infrastructure.claude_locks import (
    CONFIG_STALENESS_S,
    CREDENTIALS_STALENESS_S,
    STORAGE_WRITE_STALENESS_S,
)
from claude_acc_manager.accounts.infrastructure.diagnostics_probe import (
    OsDiagnosticsProbe,
)
from claude_acc_manager.shared.claude_contract import contract_for_version
from claude_acc_manager.shared.file_lock import exclusive_file_lock


def probe(
    tmp_path: Path,
    *,
    env: dict[str, str] | None = None,
    contract_version: tuple[int, int, int] = (2, 1, 288),
    fs_root: Path | None = None,
) -> object:
    """Probe with tmp_path as home and <tmp>/store as the store root."""
    return OsDiagnosticsProbe(
        env=env if env is not None else {},
        home=tmp_path,
        store_root=tmp_path / "store",
        contract_probe=FakeClaudeContractProbe(contract_for_version(contract_version)),
        fs_root=fs_root if fs_root is not None else tmp_path / "fsroot",
    ).probe()


def lock_by_name(facts: object, name: str) -> object:
    """The LockObservation with *name*, or fail."""
    for lock in facts.locks:  # type: ignore[attr-defined]
        if lock.name == name:
            return lock
    raise AssertionError(f"lock {name!r} missing")


class _FakeStream:
    """An isatty-able stream stand-in for the probe's tty facts."""

    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


class TestPaths:
    def test_resolves_the_live_slot_paths_from_env_and_home(self, tmp_path: Path):
        # arrange / act
        facts = probe(tmp_path)

        # assert — default layout: ~/.claude + ~/.claude.json
        assert facts.credentials_path == tmp_path / ".claude" / ".credentials.json"  # type: ignore[attr-defined]
        assert facts.config_path == tmp_path / ".claude.json"  # type: ignore[attr-defined]
        assert facts.store_root == tmp_path / "store"  # type: ignore[attr-defined]
        assert facts.accounts_dir == tmp_path / "store" / "accounts"  # type: ignore[attr-defined]

    def test_claude_config_dir_redirects_the_credentials_path(self, tmp_path: Path):
        # arrange / act
        facts = probe(tmp_path, env={"CLAUDE_CONFIG_DIR": "/scoped"})

        # assert
        assert facts.credentials_path == Path("/scoped/.credentials.json")  # type: ignore[attr-defined]

    def test_presence_flags_track_real_files(self, tmp_path: Path):
        # arrange — credentials present, config absent, store missing
        claude_home = tmp_path / ".claude"
        claude_home.mkdir()
        (claude_home / ".credentials.json").write_text("{}")

        # act
        facts = probe(tmp_path)

        # assert
        assert facts.credentials_present is True  # type: ignore[attr-defined]
        assert facts.config_present is False  # type: ignore[attr-defined]
        assert facts.store_exists is False  # type: ignore[attr-defined]
        assert facts.accounts_dir_exists is False  # type: ignore[attr-defined]

    def test_a_credentials_dir_is_not_credentials_present(self, tmp_path: Path):
        # arrange — a directory squatting on the credentials path
        claude_home = tmp_path / ".claude"
        claude_home.mkdir()
        (claude_home / ".credentials.json").mkdir()

        # act
        facts = probe(tmp_path)

        # assert — presence means a file, not just anything at the path
        assert facts.credentials_present is False  # type: ignore[attr-defined]

    def test_the_accounts_dir_reports_present_when_it_exists(self, tmp_path: Path):
        # arrange — a real store with its accounts subdir
        (tmp_path / "store" / "accounts").mkdir(parents=True)

        # act
        facts = probe(tmp_path)

        # assert — the flag is probed from the same dir the path names
        assert facts.store_exists is True  # type: ignore[attr-defined]
        assert facts.accounts_dir == tmp_path / "store" / "accounts"  # type: ignore[attr-defined]
        assert facts.accounts_dir_exists is True  # type: ignore[attr-defined]


class TestLocks:
    def test_absent_locks_report_free(self, tmp_path: Path):
        # arrange / act
        facts = probe(tmp_path)

        # assert — every observed lock is free with no age
        assert facts.locks  # type: ignore[attr-defined]
        for lock in facts.locks:  # type: ignore[attr-defined]
            assert lock.state == "free"
            assert lock.age_s is None

    def test_every_reported_lock_names_a_real_path(self, tmp_path: Path):
        # arrange / act
        facts = probe(tmp_path)

        # assert — the five locks, with the paths the swap path resolves
        names = {lock.name for lock in facts.locks}  # type: ignore[attr-defined]
        assert names == {
            "oauth refresh",
            "credentials",
            "config",
            "storage write",
            "cam ops",
        }
        by_name = {lock.name: lock for lock in facts.locks}  # type: ignore[attr-defined]
        assert by_name["oauth refresh"].path == tmp_path / ".claude" / ".oauth_refresh.lock"
        assert by_name["credentials"].path == tmp_path / ".claude.lock"
        assert by_name["config"].path == Path(f"{tmp_path}/.claude.json.lock")
        assert by_name["storage write"].path == tmp_path / ".claude" / ".storage-write"
        assert by_name["cam ops"].path == tmp_path / "store" / ".ops.lock"

    def test_a_fresh_lock_dir_reports_held(self, tmp_path: Path):
        # arrange — the oauth refresh lock, freshly created
        claude_home = tmp_path / ".claude"
        claude_home.mkdir()
        (claude_home / ".oauth_refresh.lock").mkdir()

        # act
        facts = probe(tmp_path)

        # assert
        lock = lock_by_name(facts, "oauth refresh")
        assert lock.state == "held"  # type: ignore[attr-defined]
        assert lock.path == claude_home / ".oauth_refresh.lock"  # type: ignore[attr-defined]
        assert lock.age_s is not None and lock.age_s < CREDENTIALS_STALENESS_S  # type: ignore[attr-defined]

    def test_a_lock_older_than_its_bound_reports_stale(self, tmp_path: Path):
        # arrange — config lock aged past CONFIG_STALENESS_S
        config_lock = Path(f"{tmp_path}/.claude.json.lock")
        config_lock.mkdir()
        old = time.time() - CONFIG_STALENESS_S - 10
        os.utime(config_lock, (old, old))

        # act
        facts = probe(tmp_path)

        # assert
        lock = lock_by_name(facts, "config")
        assert lock.state == "stale"  # type: ignore[attr-defined]
        assert lock.path == config_lock  # type: ignore[attr-defined]
        assert lock.age_s > CONFIG_STALENESS_S  # type: ignore[attr-defined]

    def test_credentials_and_storage_write_locks_use_their_own_bounds(self, tmp_path: Path):
        # arrange — age each past its staleness bound, inside the other's
        claude_home = tmp_path / ".claude"
        claude_home.mkdir()
        creds_lock = tmp_path / ".claude.lock"
        storage_lock = claude_home / ".storage-write"
        creds_lock.mkdir()
        storage_lock.mkdir()
        creds_old = time.time() - CREDENTIALS_STALENESS_S - 10
        storage_old = time.time() - STORAGE_WRITE_STALENESS_S - 10
        os.utime(creds_lock, (creds_old, creds_old))
        os.utime(storage_lock, (storage_old, storage_old))

        # act
        facts = probe(tmp_path)

        # assert — each lock ages against its own bound, not a shared one
        creds = lock_by_name(facts, "credentials")
        assert creds.state == "stale"  # type: ignore[attr-defined]
        assert creds.path == creds_lock  # type: ignore[attr-defined]
        storage = lock_by_name(facts, "storage write")
        assert storage.state == "stale"  # type: ignore[attr-defined]
        assert storage.path == storage_lock  # type: ignore[attr-defined]

    def test_a_lock_exactly_at_its_bound_is_still_held(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # arrange — pin the clock so the age lands exactly on the bound
        claude_home = tmp_path / ".claude"
        claude_home.mkdir()
        lock_dir = claude_home / ".oauth_refresh.lock"
        lock_dir.mkdir()
        mtime = lock_dir.stat().st_mtime
        monkeypatch.setattr(time, "time", lambda: mtime + CREDENTIALS_STALENESS_S)

        # act
        facts = probe(tmp_path)

        # assert — staleness is strictly *older than* the bound
        assert lock_by_name(facts, "oauth refresh").state == "held"  # type: ignore[attr-defined]

    def test_a_held_ops_lock_reports_held(self, tmp_path: Path):
        # arrange — another cam operation holds the flock right now
        store = tmp_path / "store"
        store.mkdir()

        # act — probe while we hold it
        with exclusive_file_lock(store / ".ops.lock", timeout_s=1.0):
            facts = probe(tmp_path)

        # assert
        lock = lock_by_name(facts, "cam ops")
        assert lock.state == "held"  # type: ignore[attr-defined]
        assert lock.path == store / ".ops.lock"  # type: ignore[attr-defined]

    def test_an_absent_ops_lock_is_created_to_probe(self, tmp_path: Path):
        # arrange — the store exists but no ops.lock file yet
        store = tmp_path / "store"
        store.mkdir()
        ops_lock = store / ".ops.lock"

        # act
        facts = probe(tmp_path)

        # assert — probing takes the flock briefly, which materializes the file
        lock = lock_by_name(facts, "cam ops")
        assert lock.state == "free"  # type: ignore[attr-defined]
        assert lock.path == ops_lock  # type: ignore[attr-defined]
        assert ops_lock.exists()


class TestProcessAndContract:
    def test_the_injected_contract_probe_supplies_the_verdict(self, tmp_path: Path):
        # arrange / act
        facts = probe(tmp_path, contract_version=(2, 2, 0))

        # assert
        assert facts.contract.version == (2, 2, 0)  # type: ignore[attr-defined]
        assert facts.contract.supported is False  # type: ignore[attr-defined]

    def test_process_facts_are_bool_and_int(self, tmp_path: Path):
        # arrange / act
        facts = probe(tmp_path)

        # assert — the real process is probed; types and coherence pin it
        assert isinstance(facts.stdin_tty, bool)  # type: ignore[attr-defined]
        assert isinstance(facts.stdout_tty, bool)  # type: ignore[attr-defined]
        assert isinstance(facts.euid, int)  # type: ignore[attr-defined]
        assert facts.euid == os.geteuid()  # type: ignore[attr-defined]
        assert isinstance(facts.in_container, bool)  # type: ignore[attr-defined]
        assert "ython" in facts.python  # type: ignore[attr-defined]
        assert facts.platform  # type: ignore[attr-defined]

    def test_distinct_stream_ttys_flow_through(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # arrange — interactive stdin, piped stdout
        monkeypatch.setattr(sys, "stdin", _FakeStream(True))
        monkeypatch.setattr(sys, "stdout", _FakeStream(False))

        # act
        facts = probe(tmp_path)

        # assert — each stream reports its own fd, and interactive needs both
        assert facts.stdin_tty is True  # type: ignore[attr-defined]
        assert facts.stdout_tty is False  # type: ignore[attr-defined]
        assert facts.interactive is False  # type: ignore[attr-defined]

    def test_both_ttys_with_a_real_term_is_interactive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # arrange
        monkeypatch.setattr(sys, "stdin", _FakeStream(True))
        monkeypatch.setattr(sys, "stdout", _FakeStream(True))

        # act
        facts = probe(tmp_path, env={"TERM": "xterm-256color"})

        # assert
        assert facts.interactive is True  # type: ignore[attr-defined]

    def test_a_dumb_term_is_never_interactive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # arrange
        monkeypatch.setattr(sys, "stdin", _FakeStream(True))
        monkeypatch.setattr(sys, "stdout", _FakeStream(True))

        # act
        facts = probe(tmp_path, env={"TERM": "dumb"})

        # assert
        assert facts.interactive is False  # type: ignore[attr-defined]

    def test_an_unknown_term_is_never_interactive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # arrange — the other terminal value that can't draw
        monkeypatch.setattr(sys, "stdin", _FakeStream(True))
        monkeypatch.setattr(sys, "stdout", _FakeStream(True))

        # act
        facts = probe(tmp_path, env={"TERM": "unknown"})

        # assert
        assert facts.interactive is False  # type: ignore[attr-defined]

    def test_a_dockerenv_marker_at_fs_root_reports_container(self, tmp_path: Path):
        # arrange — a fake filesystem root carrying the container marker
        fs_root = tmp_path / "fsroot"
        fs_root.mkdir()
        (fs_root / ".dockerenv").touch()

        # act
        facts = probe(tmp_path, fs_root=fs_root)

        # assert — the marker is probed under the injected root
        assert facts.in_container is True  # type: ignore[attr-defined]

    def test_env_arrives_whole(self, tmp_path: Path):
        # arrange / act
        facts = probe(tmp_path, env={"TERM": "dumb", "CUSTOM": "x"})

        # assert
        assert facts.env["TERM"] == "dumb"  # type: ignore[attr-defined]
        assert facts.env["CUSTOM"] == "x"  # type: ignore[attr-defined]
