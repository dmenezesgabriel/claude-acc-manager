"""``cam add`` / ``cam remove`` / ``cam enable`` / ``cam disable`` — registry mutations.

User-facing output is pinned exactly — the printed line *is* the interface
(docs/architecture.md §10), so a drift in wording is a regression, not cosmetic.
"""

from pathlib import Path

import pytest
from support.cli_rigs import run_cli as _run
from support.fake_login_launcher import FakeLoginLauncher
from support.in_memory_account_store import InMemoryAccountStore
from support.use_cases import make_account, make_use_cases

from claude_acc_manager.accounts.domain.value_objects import AccountName

_use_cases = make_use_cases
_account = make_account


class TestAddCommand:
    def test_add_registers_the_account_and_prints_confirmation(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        store = InMemoryAccountStore(tmp_path)

        # act
        code = _run(["add", "work"], _use_cases(tmp_path, store=store))

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
        code = _run(["add", "work"], use_cases)

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
        code = _run(["remove", "work"], _use_cases(tmp_path, store=store))

        # assert
        assert code == 0
        assert store.get(AccountName("work")) is None
        assert capsys.readouterr().out == "removed account 'work'\n"

    def test_remove_unknown_account_prints_a_named_error_and_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = _run(["remove", "ghost"], _use_cases(tmp_path))

        # assert
        assert code == 1
        assert capsys.readouterr().err == "error: no such account: 'ghost'\n"


class TestEnableDisableCommands:
    """cam disable/enable.

    Enabled only gates *automatic* picks; a disabled account stays a valid
    explicit ``cam switch <name>`` target.
    """

    def test_disable_marks_the_account_and_confirms(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — x is enabled but not active; y keeps rotation non-empty
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("x"))
        store.upsert(_account("y"))

        # act
        code = _run(["disable", "x"], _use_cases(tmp_path, store=store))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "disabled account 'x'\n"
        account = store.get(AccountName("x"))
        assert account is not None and not account.enabled

    def test_disable_unknown_account_errors(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = _run(["disable", "ghost"], _use_cases(tmp_path))

        # assert
        assert code == 1
        assert capsys.readouterr().err == "error: no such account: 'ghost'\n"

    def test_disable_an_already_disabled_account_is_a_quiet_noop(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("x"))
        store.set_enabled(AccountName("x"), False)

        # act
        code = _run(["disable", "x"], _use_cases(tmp_path, store=store))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "account 'x' is already disabled\n"

    def test_disable_the_active_account_notes_it_stays_live(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — x is the registry's active account; another stays enabled
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("x"))
        store.upsert(_account("y"))
        store.set_active(AccountName("x"))

        # act
        code = _run(["disable", "x"], _use_cases(tmp_path, store=store))

        # assert
        assert code == 0
        assert capsys.readouterr().out == (
            "disabled account 'x'\n"
            "  note: 'x' is the active account — it stays live until you "
            "switch away; it just won't be an automatic switch target\n"
        )

    def test_disable_the_last_enabled_account_warns_rotation_is_empty(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — x is the only enabled account left (y already disabled)
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("x"))
        store.upsert(_account("y"))
        store.set_enabled(AccountName("y"), False)

        # act
        code = _run(["disable", "x"], _use_cases(tmp_path, store=store))

        # assert
        assert code == 0
        assert capsys.readouterr().out == (
            "disabled account 'x'\n"
            "  warning: no enabled accounts remain in rotation — automatic "
            "switching has nothing to pick (re-enable one with cam enable <name>)\n"
        )

    def test_enable_returns_the_account_to_rotation(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("x"))
        store.set_enabled(AccountName("x"), False)

        # act
        code = _run(["enable", "x"], _use_cases(tmp_path, store=store))

        # assert
        assert code == 0
        assert capsys.readouterr().out == ("enabled account 'x'\n  it is back in the rotation\n")
        account = store.get(AccountName("x"))
        assert account is not None and account.enabled

    def test_enable_an_already_enabled_account_is_a_quiet_noop(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("x"))

        # act
        code = _run(["enable", "x"], _use_cases(tmp_path, store=store))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "account 'x' is already enabled\n"
