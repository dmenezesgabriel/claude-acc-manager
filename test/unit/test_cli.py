"""Unit tests for the cam CLI (add / remove / list / status).

User-facing output is pinned exactly — the printed line *is* the interface
(plan §7), so a drift in wording is a regression, not cosmetic.
"""

from pathlib import Path

import pytest
from support.fake_account_dir_reader import FakeAccountDirReader
from support.fake_active_slot import FakeActiveSlot
from support.fake_clock import FakeClock
from support.fake_login_launcher import FakeLoginLauncher
from support.in_memory_account_store import InMemoryAccountStore

from claude_acc_manager.accounts.application.use_cases.add_account import AddAccount
from claude_acc_manager.accounts.application.use_cases.list_accounts import ListAccounts
from claude_acc_manager.accounts.application.use_cases.remove_account import RemoveAccount
from claude_acc_manager.accounts.application.use_cases.status_account import StatusAccount
from claude_acc_manager.accounts.domain.entities import Account
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.cli import UseCases, run

_CREDENTIALS: dict[str, object] = {"claudeAiOauth": {"accessToken": "tok"}}
_CONFIG: dict[str, object] = {
    "oauthAccount": {"emailAddress": "user@example.com", "accountUuid": "acc-123"},
}


def _use_cases(
    tmp_path: Path,
    *,
    store: InMemoryAccountStore | None = None,
    launcher: FakeLoginLauncher | None = None,
    reader: FakeAccountDirReader | None = None,
    slot: FakeActiveSlot | None = None,
) -> UseCases:
    store = store or InMemoryAccountStore(tmp_path)
    return UseCases(
        add=AddAccount(
            launcher or FakeLoginLauncher(),
            reader or FakeAccountDirReader(credentials=_CREDENTIALS, config=_CONFIG),
            store,
            FakeClock(),
        ),
        remove=RemoveAccount(store),
        list_accounts=ListAccounts(store),
        status=StatusAccount(slot or FakeActiveSlot(config=None), store),
    )


def _account(name: str, account_uuid: str = "acc-x") -> Account:
    return Account(
        name=AccountName(name),
        email=f"{name}@example.com",
        account_uuid=account_uuid,
        organization_uuid=None,
        organization_name=None,
        added_at="2026-09-10T12:00:00Z",
        enabled=True,
    )


class TestAddCommand:
    def test_add_registers_the_account_and_prints_confirmation(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        store = InMemoryAccountStore(tmp_path)

        # act
        code = run(["add", "work"], _use_cases(tmp_path, store=store))

        # assert
        assert code == 0
        assert store.get(AccountName("work")) is not None
        assert capsys.readouterr().out == "added account 'work'\n"

    def test_add_failure_prints_the_error_to_stderr_and_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        use_cases = _use_cases(tmp_path, launcher=FakeLoginLauncher(succeeds=False))

        # act
        code = run(["add", "work"], use_cases)

        # assert
        captured = capsys.readouterr()
        assert code == 1
        assert captured.out == ""
        assert captured.err == "error: claude login did not complete for account 'work'\n"


class TestRemoveCommand:
    def test_remove_deletes_the_account_and_prints_confirmation(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))

        # act
        code = run(["remove", "work"], _use_cases(tmp_path, store=store))

        # assert
        assert code == 0
        assert store.get(AccountName("work")) is None
        assert capsys.readouterr().out == "removed account 'work'\n"

    def test_remove_unknown_account_prints_a_named_error_and_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = run(["remove", "ghost"], _use_cases(tmp_path))

        # assert
        assert code == 1
        assert capsys.readouterr().err == "error: no such account: 'ghost'\n"


class TestListCommand:
    def test_empty_store_prints_a_placeholder(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = run(["list"], _use_cases(tmp_path))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "no accounts registered\n"

    def test_lists_accounts_in_order_marking_the_active_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        store.upsert(_account("personal"))
        store.set_active(AccountName("work"))

        # act
        code = run(["list"], _use_cases(tmp_path, store=store))

        # assert
        assert code == 0
        assert capsys.readouterr().out == (
            "* work\twork@example.com\n  personal\tpersonal@example.com\n"
        )


class TestStatusCommand:
    def test_no_login_prints_a_placeholder(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = run(["status"], _use_cases(tmp_path))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "no account is logged in\n"

    def test_managed_login_names_the_registry_account(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work", account_uuid="acc-123"))
        slot = FakeActiveSlot(config=_CONFIG)

        # act
        code = run(["status"], _use_cases(tmp_path, store=store, slot=slot))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "logged in as user@example.com (managed as 'work')\n"

    def test_unmanaged_login_is_reported_as_such(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        slot = FakeActiveSlot(config=_CONFIG)

        # act
        code = run(["status"], _use_cases(tmp_path, slot=slot))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "logged in as user@example.com (not managed)\n"


class TestArgParsing:
    def test_no_subcommand_prints_usage_to_stderr_and_exits_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = run([], _use_cases(tmp_path))

        # assert
        assert code == 2
        assert capsys.readouterr().err == "usage: cam [-h] {add,remove,list,status} ...\n"

    def test_rejects_a_flag_shaped_account_name(self, tmp_path: Path):
        # act / assert — argparse treats it as an unknown option
        with pytest.raises(SystemExit):
            run(["add", "--sneaky"], _use_cases(tmp_path))


class TestHelpText:
    """--help output describes every command; the phrasing is pinned."""

    def _help(self, tmp_path: Path, capsys: pytest.CaptureFixture[str], *argv: str) -> str:
        with pytest.raises(SystemExit):
            run([*argv, "--help"], _use_cases(tmp_path))
        return capsys.readouterr().out

    def test_top_level_help_lists_the_prog_description_and_commands(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        text = self._help(tmp_path, capsys)

        # assert
        assert text.startswith("usage: cam [-h] {add,remove,list,status} ...\n")
        assert "\nmanage Claude Code OAuth accounts\n" in text
        assert "    add                 register an account via an isolated claude login\n" in text
        assert "    remove              unregister an account and delete its login dir\n" in text
        assert "    list                list registered accounts\n" in text
        assert "    status              show the account the live claude slot uses\n" in text

    def test_add_and_remove_help_document_the_name_argument(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act / assert
        for command in ("add", "remove"):
            text = self._help(tmp_path, capsys, command)
            assert text.startswith(f"usage: cam {command} [-h] name\n")
            assert "  name        account name\n" in text
