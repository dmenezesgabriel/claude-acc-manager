"""Wiring tests for the composition root (claude_acc_manager.__main__).

The module is excluded from the coverage floor and the mutation gate (it holds
the one ambient os.environ / Path.home() read the codebase's seams exist to
avoid), so its wiring is pinned here for real instead: build it against a
hermetic env + home and prove each adapter resolves against the right path.
"""

import importlib
import json
import os
import tomllib
from pathlib import Path

import pytest

from claude_acc_manager.__main__ import build_use_cases
from claude_acc_manager.accounts.application.use_cases.add_account import AddAccount
from claude_acc_manager.accounts.application.use_cases.collect_accounts_view import (
    CollectAccountsView,
)
from claude_acc_manager.accounts.application.use_cases.list_accounts import ListAccounts
from claude_acc_manager.accounts.application.use_cases.quarantine_dead_lineage import (
    QuarantineDeadLineage,
)
from claude_acc_manager.accounts.application.use_cases.remove_account import RemoveAccount
from claude_acc_manager.accounts.application.use_cases.set_account_enabled import (
    SetAccountEnabled,
)
from claude_acc_manager.accounts.application.use_cases.status_account import StatusAccount
from claude_acc_manager.accounts.application.use_cases.switch_account import SwitchAccount
from claude_acc_manager.cli import ProcessContext, run


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    return home


def _registry(store_dir: Path, *names: str) -> None:
    store_dir.mkdir(parents=True)
    (store_dir / "registry.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "order": list(names),
                "active": None,
                "accounts": {
                    name: {
                        "email": f"{name}@e.com",
                        "account_uuid": f"uuid-{name}",
                        "organization_uuid": None,
                        "organization_name": None,
                        "added_at": "2026-09-10T12:00:00Z",
                        "enabled": True,
                    }
                    for name in names
                },
                "quarantined": [],
            }
        ),
        encoding="utf-8",
    )


def _stub_claude(tmp_path: Path, version: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Put a stub ``claude`` answering ``<version> (Claude Code)`` on PATH."""
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir()
    stub = bin_dir / "claude"
    stub.write_text(f'#!/bin/sh\necho "{version} (Claude Code)"\n', encoding="utf-8")
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("CAM_ASSUME_CLAUDE_CONTRACT", raising=False)


class TestCamEntryPoint:
    """The [project.scripts] cam target actually resolves to a callable."""

    def test_console_script_target_is_importable_and_callable(self):
        # arrange — read the entry point the packaging metadata declares
        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        target = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["scripts"]["cam"]
        module_name, _, attr = target.partition(":")

        # act
        entry = getattr(importlib.import_module(module_name), attr)

        # assert
        assert callable(entry)


class TestBuildUseCases:
    """build_use_cases wires the four use cases to path-correct adapters."""

    def test_wires_all_use_cases(self, tmp_path: Path):
        # arrange / act
        use_cases = build_use_cases({"XDG_DATA_HOME": str(tmp_path)}, _home(tmp_path))

        # assert
        assert isinstance(use_cases.add, AddAccount)
        assert isinstance(use_cases.remove, RemoveAccount)
        assert isinstance(use_cases.list_accounts, ListAccounts)
        assert isinstance(use_cases.collect_view, CollectAccountsView)
        assert isinstance(use_cases.status, StatusAccount)
        assert isinstance(use_cases.switch, SwitchAccount)
        assert isinstance(use_cases.quarantine_dead_lineage, QuarantineDeadLineage)
        assert isinstance(use_cases.set_enabled, SetAccountEnabled)
        assert use_cases.account_store is not None
        assert use_cases.account_files is not None
        assert use_cases.usage_cache is not None
        assert use_cases.usage_clock is not None

    def test_store_reads_the_registry_under_the_xdg_data_home(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — a registry at <XDG_DATA_HOME>/claude-acc-manager/ (docs/architecture.md §3)
        store_dir = tmp_path / "xdg" / "claude-acc-manager"
        store_dir.mkdir(parents=True)
        (store_dir / "registry.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "order": ["work"],
                    "active": None,
                    "accounts": {
                        "work": {
                            "email": "w@e.com",
                            "account_uuid": "a1",
                            "organization_uuid": None,
                            "organization_name": None,
                            "added_at": "2026-09-10T12:00:00Z",
                            "enabled": True,
                        }
                    },
                    "quarantined": [],
                }
            ),
            encoding="utf-8",
        )
        use_cases = build_use_cases({"XDG_DATA_HOME": str(tmp_path / "xdg")}, _home(tmp_path))

        # act
        code = run(["list"], use_cases, process=ProcessContext(euid=1000, in_container=False))

        # assert
        assert code == 0
        assert "work" in capsys.readouterr().out

    def test_status_reads_the_live_slot_from_the_given_home(self, tmp_path: Path):
        # arrange — ~/.claude.json with an oauthAccount block under *home*
        home = _home(tmp_path)
        (home / ".claude.json").write_text(
            '{"oauthAccount": {"emailAddress": "u@e.com", "accountUuid": "acc-9"}}',
            encoding="utf-8",
        )
        use_cases = build_use_cases({"XDG_DATA_HOME": str(tmp_path / "xdg")}, home)

        # act
        status = use_cases.status.execute()

        # assert
        assert status is not None
        assert status.email == "u@e.com"
        assert status.managed_as is None

    def test_switch_moves_the_live_login_through_real_adapters(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ):
        # arrange — x live in ~/.claude + ~/.claude.json, y parked under the
        # store; the whole move model exercised end to end on real files.
        # The wired contract probe subprocesses `claude --version`, so a stub
        # in the verified band stands in for a real install (CI has none).
        home = _home(tmp_path)
        _stub_claude(tmp_path, "2.1.288", monkeypatch)
        (home / ".claude").mkdir()
        (home / ".claude" / ".credentials.json").write_text(
            json.dumps({"claudeAiOauth": {"accessToken": "at-x", "refreshToken": "rt-x"}}),
            encoding="utf-8",
        )
        (home / ".claude.json").write_text(
            json.dumps({"oauthAccount": {"emailAddress": "x@e.com", "accountUuid": "a1"}}),
            encoding="utf-8",
        )
        store_dir = tmp_path / "xdg" / "claude-acc-manager"
        y_dir = store_dir / "accounts" / "y"
        x_dir = store_dir / "accounts" / "x"
        y_dir.mkdir(parents=True)
        x_dir.mkdir(parents=True)
        for name, uuid in (("x", "a1"), ("y", "a2")):
            account_dir = store_dir / "accounts" / name
            (account_dir / ".claude.json").write_text(
                json.dumps(
                    {"oauthAccount": {"emailAddress": f"{name}@e.com", "accountUuid": uuid}}
                ),
                encoding="utf-8",
            )
        (y_dir / ".credentials.json").write_text(
            json.dumps({"claudeAiOauth": {"accessToken": "at-y", "refreshToken": "rt-y"}}),
            encoding="utf-8",
        )
        (store_dir / "registry.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "order": ["x", "y"],
                    "active": "x",
                    "accounts": {
                        name: {
                            "email": f"{name}@e.com",
                            "account_uuid": uuid,
                            "organization_uuid": None,
                            "organization_name": None,
                            "added_at": "2026-09-10T12:00:00Z",
                            "enabled": True,
                        }
                        for name, uuid in (("x", "a1"), ("y", "a2"))
                    },
                    "quarantined": [],
                }
            ),
            encoding="utf-8",
        )
        use_cases = build_use_cases({"XDG_DATA_HOME": str(tmp_path / "xdg")}, home)

        # act
        code = run(
            ["switch", "y"], use_cases, process=ProcessContext(euid=1000, in_container=False)
        )

        # assert — the move model, end to end: one lineage copy per account
        assert code == 0
        assert "switched to 'y' (was 'x')" in capsys.readouterr().out
        live = json.loads((home / ".claude" / ".credentials.json").read_text(encoding="utf-8"))
        assert live["claudeAiOauth"]["refreshToken"] == "rt-y"
        assert not (y_dir / ".credentials.json").exists()
        moved_back = json.loads((x_dir / ".credentials.json").read_text(encoding="utf-8"))
        assert moved_back["claudeAiOauth"]["refreshToken"] == "rt-x"
        registry = json.loads((store_dir / "registry.json").read_text(encoding="utf-8"))
        assert registry["active"] == "y"


class TestClaudeContractWiring:
    """build_use_cases wires real subprocess probes — __main__ sits outside
    the mutation gate, so the wire itself is what these tests pin: a stub
    ``claude`` answering an out-of-band version must produce the versioned
    refusal through ``run()``, which no missing, fake, or wrong-executable
    wire can produce.
    """

    def test_switch_is_refused_through_the_wired_probe(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ):
        # arrange — 'y' registered; the stub claude reports 2.2.0, outside
        # the verified band, so the gate refuses before any file mutation
        home = _home(tmp_path)
        _registry(tmp_path / "xdg" / "claude-acc-manager", "y")
        _stub_claude(tmp_path, "2.2.0", monkeypatch)
        use_cases = build_use_cases({"XDG_DATA_HOME": str(tmp_path / "xdg")}, home)

        # act
        code = run(
            ["switch", "y"], use_cases, process=ProcessContext(euid=1000, in_container=False)
        )

        # assert
        assert code == 1
        err = capsys.readouterr().err
        assert "claude 2.2.0 is newer than cam's verified contract" in err
        assert "CAM_ASSUME_CLAUDE_CONTRACT" in err
        assert not (home / ".claude").exists()

    def test_usage_refresh_is_refused_through_the_wired_probe(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ):
        # arrange — parked 'work' credential long expired; refreshing would
        # spend the one-time grant, so the gate must refuse first
        home = _home(tmp_path)
        store_dir = tmp_path / "xdg" / "claude-acc-manager"
        _registry(store_dir, "work")
        work_dir = store_dir / "accounts" / "work"
        work_dir.mkdir(parents=True)
        (work_dir / ".credentials.json").write_text(
            json.dumps(
                {
                    "claudeAiOauth": {
                        "accessToken": "at",
                        "refreshToken": "rt",
                        "expiresAt": 0,
                    }
                }
            ),
            encoding="utf-8",
        )
        _stub_claude(tmp_path, "2.2.0", monkeypatch)
        use_cases = build_use_cases({"XDG_DATA_HOME": str(tmp_path / "xdg")}, home)

        # act
        code = run(
            ["usage", "work"], use_cases, process=ProcessContext(euid=1000, in_container=False)
        )

        # assert
        assert code == 1
        assert "claude 2.2.0 is newer than cam's verified contract" in capsys.readouterr().err
