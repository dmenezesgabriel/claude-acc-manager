"""Wiring tests for the composition root (claude_acc_manager.__main__).

The module is excluded from the coverage floor and the mutation gate (it holds
the one ambient os.environ / Path.home() read the codebase's seams exist to
avoid), so its wiring is pinned here for real instead: build it against a
hermetic env + home and prove each adapter resolves against the right path.
"""

import json
from pathlib import Path

import pytest

from claude_acc_manager.__main__ import build_use_cases
from claude_acc_manager.accounts.application.use_cases.add_account import AddAccount
from claude_acc_manager.accounts.application.use_cases.list_accounts import ListAccounts
from claude_acc_manager.accounts.application.use_cases.remove_account import RemoveAccount
from claude_acc_manager.accounts.application.use_cases.status_account import StatusAccount
from claude_acc_manager.cli import run


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    return home


class TestBuildUseCases:
    """build_use_cases wires the four use cases to path-correct adapters."""

    def test_wires_all_four_use_cases(self, tmp_path: Path):
        # arrange / act
        use_cases = build_use_cases({"XDG_DATA_HOME": str(tmp_path)}, _home(tmp_path))

        # assert
        assert isinstance(use_cases.add, AddAccount)
        assert isinstance(use_cases.remove, RemoveAccount)
        assert isinstance(use_cases.list_accounts, ListAccounts)
        assert isinstance(use_cases.status, StatusAccount)

    def test_store_reads_the_registry_under_the_xdg_data_home(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — a registry at <XDG_DATA_HOME>/claude-acc-manager/ (plan §4.3)
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
