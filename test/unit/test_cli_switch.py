"""``cam switch`` — the switch transaction through the dispatch layer.

User-facing output is pinned exactly — the printed line *is* the interface
(docs/architecture.md §10), so a drift in wording is a regression, not cosmetic.
"""

import json
from pathlib import Path

import pytest
from support.cli_rigs import config_for as _config_for
from support.cli_rigs import park_account as _park
from support.cli_rigs import run_cli as _run
from support.fake_account_dir import FakeAccountDir
from support.fake_active_slot import FakeActiveSlot
from support.fake_claude_contract import FakeClaudeContractProbe
from support.fake_ops_lock import FakeOpsLock
from support.in_memory_account_store import InMemoryAccountStore
from support.use_cases import credentials_for, make_account, make_use_cases

from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.shared.claude_contract import contract_for_version

_use_cases = make_use_cases
_account = make_account
_creds_for = credentials_for


class TestSwitchCommand:
    def test_switches_to_the_named_account(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — x live, y parked
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))

        # act
        code = _run(["switch", "y"], _use_cases(tmp_path, store=store, reader=reader, slot=slot))

        # assert — the move model: y's lineage now lives in the live slot
        assert code == 0
        assert capsys.readouterr().out == "switched to 'y' (was 'x')\n"
        assert slot.read_credentials() == _creds_for("y")
        y_dir = store.account_dir(AccountName("y"))
        x_dir = store.account_dir(AccountName("x"))
        assert reader.read_credentials(y_dir) is None
        assert reader.read_credentials(x_dir) == _creds_for("x")
        active = store.active()
        assert active is not None and active.name.value == "y"

    def test_unknown_target_prints_a_named_error_and_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = _run(["switch", "ghost"], _use_cases(tmp_path))

        # assert
        assert code == 1
        assert capsys.readouterr().err == "error: no such account: 'ghost'\n"

    def test_a_target_and_a_strategy_together_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "y")

        # act
        code = _run(
            ["switch", "y", "--strategy", "best"],
            _use_cases(tmp_path, store=store, reader=reader),
        )

        # assert
        assert code == 1
        assert "cannot combine an explicit target 'y' with strategy 'best'" in (
            capsys.readouterr().err
        )

    def test_a_lock_timeout_prints_a_named_error_and_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — another cam operation holds the store's ops lock
        ops = FakeOpsLock()
        ops.fail = True
        store = InMemoryAccountStore(tmp_path)
        store.upsert(make_account("y"))

        # act
        code = _run(["switch", "y"], _use_cases(tmp_path, store=store, ops=ops))

        # assert — a clean error line, never a traceback
        assert code == 1
        assert capsys.readouterr().err == "error: ops lock held past timeout\n"

    def test_a_lock_timeout_under_json_emits_the_envelope(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        ops = FakeOpsLock()
        ops.fail = True
        store = InMemoryAccountStore(tmp_path)
        store.upsert(make_account("y"))

        # act
        code = _run(["switch", "y", "--json"], _use_cases(tmp_path, store=store, ops=ops))

        # assert
        captured = capsys.readouterr()
        assert code == 1
        assert captured.err == ""
        assert json.loads(captured.out) == {
            "schemaVersion": 1,
            "error": {"type": "TimeoutError", "message": "ops lock held past timeout"},
        }

    def test_bare_switch_rotates_to_the_next_registered_account(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — x live, y parked after it in registry order
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))

        # act
        code = _run(["switch"], _use_cases(tmp_path, store=store, reader=reader, slot=slot))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "switched to 'y' (was 'x')\n"

    def test_an_unmanaged_live_login_is_preserved(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — the live slot holds a foreign login, not a managed account
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        slot = FakeActiveSlot(credentials=_creds_for("foreign"), config=_config_for("acc-foreign"))

        # act
        code = _run(["switch", "x"], _use_cases(tmp_path, store=store, reader=reader, slot=slot))

        # assert
        assert code == 0
        assert capsys.readouterr().out == (
            "switched to 'x' (was an unmanaged login)\n"
            "the previous unmanaged login was preserved under /unclaimed/fake-1.json\n"
        )

    def test_switching_to_the_live_account_reports_already_active(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))

        # act
        code = _run(["switch", "x"], _use_cases(tmp_path, store=store, reader=reader, slot=slot))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "'x' is already the active account\n"

    def test_a_scoped_shell_is_refused_with_an_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — `cam` inside CLAUDE_CONFIG_DIR=accounts/x resolves "live"
        # to x's parked dir
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        scoped = store.account_dir(AccountName("x")) / ".credentials.json"
        slot = FakeActiveSlot(
            credentials=_creds_for("x"),
            config=_config_for("acc-x"),
            live_credentials_path=scoped,
        )

        # act
        code = _run(["switch", "y"], _use_cases(tmp_path, store=store, reader=reader, slot=slot))

        # assert
        assert code == 1
        assert "scoped shell" in capsys.readouterr().err

    def test_model_flag_is_accepted(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange — --model is parsed for flag parity; it is not persisted
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))

        # act
        code = _run(
            ["switch", "y", "--model", "claude-opus-4"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot),
        )

        # assert
        assert code == 0
        assert capsys.readouterr().out == "switched to 'y' (was 'x')\n"

    def test_switch_with_no_prior_login_reports_no_login(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — the live slot is empty; x is parked
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        slot = FakeActiveSlot()

        # act
        code = _run(["switch", "x"], _use_cases(tmp_path, store=store, reader=reader, slot=slot))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "switched to 'x' (was no login)\n"

    def test_switch_help_documents_its_flags(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        with pytest.raises(SystemExit):
            _run(["switch", "--help"], _use_cases(tmp_path))
        text = capsys.readouterr().out

        # assert — usage line pins nargs="?", the choices literal, both
        # flags; the help-text pins end at a newline so an XX-mutated or
        # dropped string can't contain them
        assert (
            "usage: cam switch [-h] [--strategy {best,next-available}] [--dry-run] [--json]\n"
            "                  [--model MODEL]\n"
            "                  [name]\n" in text
        )
        assert "account name (omit to rotate)\n" in text
        assert "instead of naming one\n" in text
        assert "describe the switch without applying it\n" in text
        assert "emit the schema-v1 JSON payload\n" in text
        assert "persisted yet\n" in text

    def test_an_unknown_strategy_is_rejected(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act / assert — argparse's choices= gate exits 2 before the use case
        with pytest.raises(SystemExit) as exited:
            _run(["switch", "--strategy", "bogus"], _use_cases(tmp_path))
        assert exited.value.code == 2
        assert "invalid choice" in capsys.readouterr().err

    def test_a_wiped_live_credential_is_quarantined_not_preserved(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — x's live tokens were wiped in place by an invalid_grant;
        # nothing recoverable, so the lineage tombstones instead of parking
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        _park(store, reader, "y")
        wiped = {"claudeAiOauth": {"accessToken": "", "refreshToken": "", "expiresAt": 1}}
        slot = FakeActiveSlot(credentials=wiped, config=_config_for("acc-x"))

        # act
        code = _run(["switch", "y"], _use_cases(tmp_path, store=store, reader=reader, slot=slot))

        # assert
        assert code == 0
        assert capsys.readouterr().out == (
            "switched to 'y' (was 'x')\nquarantined the wiped credential of 'x'\n"
        )
        assert [entry.name for entry in store.quarantined()] == ["x"]

    def test_a_refused_contract_prints_the_reason_and_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — an out-of-band claude: the switch must refuse as a
        # clean error, never a traceback
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "y")

        # act
        code = _run(
            ["switch", "y"],
            _use_cases(
                tmp_path,
                store=store,
                reader=reader,
                contract_probe=FakeClaudeContractProbe(contract_for_version((0, 2, 126))),
            ),
        )

        # assert
        assert code == 1
        err = capsys.readouterr().err
        assert err.startswith("error: claude 0.2.126 predates the credential contract")
        assert "upgrade claude" in err
