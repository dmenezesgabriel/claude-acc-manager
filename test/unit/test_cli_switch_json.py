"""``cam switch --json`` — schema-v1 payloads and typed error envelopes.

User-facing output is pinned exactly — the printed line *is* the interface
(docs/architecture.md §10), so a drift in wording is a regression, not cosmetic.
"""

import json
from pathlib import Path

import pytest
from support.cli_rigs import cache_usage as _cache_usage
from support.cli_rigs import config_for as _config_for
from support.cli_rigs import park_account as _park
from support.cli_rigs import run_cli as _run
from support.fake_account_dir import FakeAccountDir
from support.fake_active_slot import FakeActiveSlot
from support.fake_claude_contract import FakeClaudeContractProbe
from support.in_memory_account_store import InMemoryAccountStore
from support.in_memory_usage_cache import InMemoryUsageCache
from support.use_cases import SEEDED_CONFIG, credentials_for, make_use_cases

from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.shared.claude_contract import contract_for_version

_CONFIG = SEEDED_CONFIG
_use_cases = make_use_cases
_creds_for = credentials_for


class TestSwitchJsonCommand:
    """cam switch --json — the outcome as schema-v1 data plus the human line."""

    def _switched_pair(
        self, tmp_path: Path
    ) -> tuple[InMemoryAccountStore, FakeAccountDir, FakeActiveSlot]:
        """x live, y parked — the standard switchable arrange."""
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))
        return store, reader, slot

    def test_a_refused_contract_emits_the_typed_error_envelope(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — an out-of-band claude; the envelope's type must name the
        # contract refusal, not the generic ValueError bucket
        store, reader, _ = self._switched_pair(tmp_path)

        # act
        code = _run(
            ["switch", "y", "--json"],
            _use_cases(
                tmp_path,
                store=store,
                reader=reader,
                contract_probe=FakeClaudeContractProbe(contract_for_version((2, 2, 0))),
            ),
        )

        # assert
        captured = capsys.readouterr()
        assert code == 1
        assert captured.err == ""
        payload = json.loads(captured.out)
        assert payload["schemaVersion"] == 1
        assert payload["error"]["type"] == "UnsupportedClaudeVersion"
        assert payload["error"]["message"].startswith(
            "claude 2.2.0 is newer than cam's verified contract"
        )
        assert "CAM_ASSUME_CLAUDE_CONTRACT" in payload["error"]["message"]

    def test_a_switch_emits_the_full_payload(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        store, reader, slot = self._switched_pair(tmp_path)

        # act
        code = _run(
            ["switch", "y", "--json"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot),
        )

        # assert — one machine-readable object; the human line rides as message
        captured = capsys.readouterr()
        assert code == 0
        assert captured.err == ""
        assert json.loads(captured.out) == {
            "schemaVersion": 1,
            "dryRun": False,
            "switched": True,
            "outcome": "switched",
            "from": {"name": "x", "email": "x@example.com"},
            "to": {"name": "y", "email": "y@example.com"},
            "unmanagedLive": False,
            "preservedTo": None,
            "strategy": None,
            "skipped": [],
            "quarantined": [],
            "message": "switched to 'y' (was 'x')",
        }

    def test_a_dry_run_marks_dry_run_and_moves_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        store, reader, slot = self._switched_pair(tmp_path)

        # act
        code = _run(
            ["switch", "y", "--dry-run", "--json"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot),
        )

        # assert
        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload["dryRun"] is True
        assert payload["switched"] is True
        assert payload["message"] == "dry run: switched to 'y' (was 'x')"
        assert slot.read_credentials() == _creds_for("x")
        assert reader.read_credentials(store.account_dir(AccountName("y"))) == _creds_for("y")

    def test_an_unmanaged_outgoing_login_sets_from_null(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — the live slot holds a foreign login
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        slot = FakeActiveSlot(credentials=_creds_for("foreign"), config=_config_for("acc-foreign"))

        # act
        code = _run(
            ["switch", "x", "--json"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot),
        )

        # assert
        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload["switched"] is True
        assert payload["from"] is None
        assert payload["unmanagedLive"] is True
        assert payload["preservedTo"] == "/unclaimed/fake-1.json"
        assert payload["message"] == "switched to 'x' (was an unmanaged login)"

    def test_already_active_is_a_noop_payload(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        store, reader, slot = self._switched_pair(tmp_path)

        # act
        code = _run(
            ["switch", "x", "--json"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot),
        )

        # assert
        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload["switched"] is False
        assert payload["outcome"] == "already-active"
        assert payload["from"] == {"name": "x", "email": "x@example.com"}
        assert payload["to"] == {"name": "x", "email": "x@example.com"}
        assert payload["message"] == "'x' is already the active account"

    def test_a_stay_outcome_carries_the_strategy_and_skipped(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — every candidate measured at its limit
        store, reader, slot = self._switched_pair(tmp_path)
        cache = InMemoryUsageCache()
        _cache_usage(cache, "y", 100.0)

        # act
        code = _run(
            ["switch", "--strategy", "next-available", "--json"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot, usage_cache=cache),
        )

        # assert
        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload["switched"] is False
        assert payload["outcome"] == "candidates-exhausted"
        assert payload["to"] is None
        assert payload["strategy"] == "next-available"
        assert payload["skipped"] == [{"name": "y", "reason": "at-limit"}]
        assert payload["message"] == "every candidate is at its limit"

    def test_unknown_target_emits_the_envelope_on_stdout(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = _run(["switch", "ghost", "--json"], _use_cases(tmp_path))

        # assert
        captured = capsys.readouterr()
        assert code == 1
        assert captured.err == ""
        assert json.loads(captured.out) == {
            "schemaVersion": 1,
            "error": {"type": "KeyError", "message": "no such account: 'ghost'"},
        }

    def test_a_scoped_shell_emits_the_envelope_on_stdout(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — `cam` inside CLAUDE_CONFIG_DIR=accounts/x
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
        code = _run(
            ["switch", "y", "--json"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot),
        )

        # assert
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert code == 1
        assert captured.err == ""
        assert payload["schemaVersion"] == 1
        assert payload["error"]["type"] == "ValueError"
        assert "scoped shell" in payload["error"]["message"]

    def test_a_wiped_lineage_lists_quarantined(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — x's live tokens were wiped in place; the switch tombstones it
        store, reader, slot = self._switched_pair(tmp_path)
        slot.write_credentials(
            {"claudeAiOauth": {"accessToken": "", "refreshToken": "", "expiresAt": 1}}
        )

        # act
        code = _run(
            ["switch", "y", "--json"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot),
        )

        # assert
        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload["quarantined"] == ["x"]
        assert payload["switched"] is True
        assert [entry.name for entry in store.quarantined()] == ["x"]
