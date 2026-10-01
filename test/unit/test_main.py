"""Wiring tests for the composition root (claude_acc_manager.__main__).

The module is excluded from the coverage floor and the mutation gate (it holds
the one ambient os.environ / Path.home() read the codebase's seams exist to
avoid), so its wiring is pinned here for real instead: build it against a
hermetic env + home and prove each adapter resolves against the right path.
"""

import importlib
import json
import tomllib
from pathlib import Path

import pytest

from claude_acc_manager.__main__ import build_use_cases
from claude_acc_manager.accounts.application.use_cases.add_account import AddAccount
from claude_acc_manager.accounts.application.use_cases.list_accounts import ListAccounts
from claude_acc_manager.accounts.application.use_cases.quarantine_account import (
    QuarantineAccount,
)
from claude_acc_manager.accounts.application.use_cases.remove_account import RemoveAccount
from claude_acc_manager.accounts.application.use_cases.status_account import StatusAccount
from claude_acc_manager.accounts.application.use_cases.switch_account import SwitchAccount
from claude_acc_manager.cli import run


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    return home


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
        assert isinstance(use_cases.status, StatusAccount)
        assert isinstance(use_cases.switch, SwitchAccount)
        assert isinstance(use_cases.quarantine, QuarantineAccount)
        assert use_cases.account_store is not None
        assert use_cases.account_files is not None
        assert use_cases.usage_cache is not None

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
        code = run(["list"], use_cases)

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
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — x live in ~/.claude + ~/.claude.json, y parked under the
        # store; the whole move model exercised end to end on real files
        home = _home(tmp_path)
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
        code = run(["switch", "y"], use_cases)

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
