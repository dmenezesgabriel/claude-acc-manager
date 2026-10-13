"""``cam usage --json`` — schema-v1 payload, envelope errors, pure stdout.

User-facing output is pinned exactly — the printed line *is* the interface
(docs/architecture.md §10), so a drift in wording is a regression, not cosmetic.
"""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from support.cli_rigs import config_for as _config_for
from support.cli_rigs import run_cli as _run
from support.controllable_clock import ControllableClock
from support.fake_account_dir import FakeAccountDir
from support.fake_claude_contract import FakeClaudeContractProbe
from support.fake_credential_store import FakeCredentialStore
from support.fake_token_refresher import FakeTokenRefresher
from support.fake_usage_api import FakeUsageApi
from support.in_memory_account_store import InMemoryAccountStore
from support.in_memory_usage_cache import InMemoryUsageCache
from support.interrupting_fetch_usage import InterruptingFetchUsage
from support.interrupting_list_accounts import InterruptingListAccounts
from support.use_cases import (
    SEEDED_SNAPSHOT,
    make_account,
    make_fetch_usage,
    make_use_cases,
    stored_credential,
)

from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.cli import ProcessContext, run
from claude_acc_manager.shared.claude_contract import contract_for_version
from claude_acc_manager.usage.application.ports import AnthropicApiError
from claude_acc_manager.usage.application.use_cases.fetch_account_usage import FetchAccountUsage
from claude_acc_manager.usage.domain.usage_cache_entry import EMPTY_USAGE_CACHE_ENTRY
from claude_acc_manager.usage.domain.usage_snapshot import ScopedWindow, UsageSnapshot, UsageWindow

_USAGE_SNAPSHOT = SEEDED_SNAPSHOT
_use_cases = make_use_cases
_fetch_usage = make_fetch_usage
_account = make_account
_stored_credential = stored_credential


class TestUsageJsonCommand:
    """cam usage --json — schema-v1 payload, envelope errors, pure stdout.

    Contract: one json.dumps object on stdout carrying
    schemaVersion 1, camelCase keys; handled failures emit the error
    envelope on stdout (exit 1) so `| jq` pipelines stay parseable.
    """

    def test_emits_the_usage_payload(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        snapshot = UsageSnapshot(
            five_hour=UsageWindow(pct=62.0, resets_at="2026-05-23T13:30:00Z"),
            seven_day=UsageWindow(pct=27.0, resets_at="2026-05-27T00:00:00Z"),
            scoped=(ScopedWindow("Fable", 84.0, "2026-05-29T00:00:00Z"),),
        )
        credentials = FakeCredentialStore(credentials={"work": _stored_credential()})
        fetch_usage = _fetch_usage(
            usage_api=FakeUsageApi(snapshot=snapshot), credentials=credentials
        )

        # act
        code = _run(
            ["usage", "work", "--json"],
            _use_cases(tmp_path, store=store, fetch_usage=fetch_usage),
        )

        # assert — the whole object is the contract; resetsAt only ships when set
        captured = capsys.readouterr()
        assert code == 0
        assert captured.err == ""
        # the serialization itself is pinned — indent=2, keys in schema order
        assert captured.out.startswith('{\n  "schemaVersion": 1,\n')
        assert json.loads(captured.out) == {
            "schemaVersion": 1,
            "account": "work",
            "usageStatus": "ok",
            "usage": {
                "fiveHour": {"pct": 62.0, "resetsAt": "2026-05-23T13:30:00Z"},
                "sevenDay": {"pct": 27.0, "resetsAt": "2026-05-27T00:00:00Z"},
                "scoped": [{"name": "Fable", "pct": 84.0, "resetsAt": "2026-05-29T00:00:00Z"}],
            },
            "stale": False,
            "usageError": None,
            "permanentAuthError": False,
            "quarantined": False,
        }

    def test_unknown_account_emits_the_error_envelope_on_stdout(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = _run(["usage", "ghost", "--json"], _use_cases(tmp_path))

        # assert — stdout stays machine-readable, stderr stays silent
        captured = capsys.readouterr()
        assert code == 1
        assert captured.err == ""
        assert captured.out.startswith('{\n  "schemaVersion": 1,\n')
        assert json.loads(captured.out) == {
            "schemaVersion": 1,
            "error": {"type": "KeyError", "message": "no such account: 'ghost'"},
        }

    def test_no_credential_reads_unavailable(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        fetch_usage = _fetch_usage(credentials=FakeCredentialStore())

        # act
        code = _run(
            ["usage", "work", "--json"],
            _use_cases(tmp_path, store=store, fetch_usage=fetch_usage),
        )

        # assert
        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload["usageStatus"] == "unavailable"
        assert payload["usage"] is None
        assert payload["usageError"] == "no-credential"
        assert payload["stale"] is False

    def test_a_stale_last_good_still_reads_ok_and_flags_stale(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — frozen last_good served after a 429
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(EMPTY_USAGE_CACHE_ENTRY, last_good=_USAGE_SNAPSHOT, fetched_at_s=999_800.0),
        )
        credentials = FakeCredentialStore(credentials={"work": _stored_credential()})
        fetch_usage = FetchAccountUsage(
            FakeUsageApi(error=AnthropicApiError(429, None)),
            FakeTokenRefresher(),
            credentials,
            cache,
            ControllableClock(now_epoch_s=1_000_000.0),
            FakeClaudeContractProbe(contract_for_version((2, 1, 288))),
            threshold=90.0,
        )

        # act
        code = _run(
            ["usage", "work", "--json"],
            _use_cases(tmp_path, store=store, fetch_usage=fetch_usage),
        )

        # assert
        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload["usageStatus"] == "ok"
        assert payload["usage"] == {"fiveHour": {"pct": 10.0}, "scoped": []}
        assert payload["stale"] is True
        assert payload["usageError"] == "http-429"

    def test_permanent_auth_error_folds_the_quarantine_into_the_payload(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — parked credential + invalid_grant on refresh (the
        # dead-lineage arrange from the plain-usage twin of this test)
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        reader = FakeAccountDir()
        reader.put(
            store.account_dir(AccountName("work")),
            credentials={"claudeAiOauth": {"accessToken": "at", "refreshToken": "rt-dead"}},
            config=_config_for("acc-x"),
        )
        credentials = FakeCredentialStore(
            credentials={"work": _stored_credential(expires_at_ms=0.0)}
        )
        fetch_usage = _fetch_usage(
            credentials=credentials,
            refresher=FakeTokenRefresher(error=AnthropicApiError(400, "invalid_grant")),
        )

        # act
        code = _run(
            ["usage", "work", "--json"],
            _use_cases(tmp_path, store=store, reader=reader, fetch_usage=fetch_usage),
        )

        # assert — the tombstone lands in the payload; no human line leaks
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert code == 0
        assert payload["permanentAuthError"] is True
        assert payload["quarantined"] is True
        assert payload["usageStatus"] == "unavailable"
        assert store.quarantined()[0].name == "work"

    def test_value_error_under_json_emits_the_envelope_on_stdout(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act — a name the value object rejects raises ValueError mid-handler
        code = _run(["usage", "bad name", "--json"], _use_cases(tmp_path))

        # assert
        captured = capsys.readouterr()
        assert code == 1
        assert captured.err == ""
        assert json.loads(captured.out) == {
            "schemaVersion": 1,
            "error": {
                "type": "ValueError",
                "message": (
                    "account name 'bad name' may only contain letters, digits, '-', '_' and '.'"
                ),
            },
        }

    def test_keyboard_interrupt_on_a_jsonless_command_writes_to_stdout(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act — list has no --json flag: the note is normal user-facing output
        code = _run(["list"], _use_cases(tmp_path, list_accounts=InterruptingListAccounts()))

        # assert
        captured = capsys.readouterr()
        assert code == 130
        assert captured.out == "\noperation cancelled\n"
        assert captured.err == ""

    def test_keyboard_interrupt_writes_the_note_to_stderr_and_exits_130(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — Ctrl-C lands mid-fetch
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))

        # act
        code = _run(
            ["usage", "work", "--json"],
            _use_cases(tmp_path, store=store, fetch_usage=InterruptingFetchUsage()),
        )

        # assert — stdout stays parseable: the note goes to stderr
        captured = capsys.readouterr()
        assert code == 130
        assert captured.out == ""
        assert captured.err == "\noperation cancelled\n"

    def test_keyboard_interrupt_without_json_writes_the_note_to_stdout(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))

        # act
        code = _run(
            ["usage", "work"],
            _use_cases(tmp_path, store=store, fetch_usage=InterruptingFetchUsage()),
        )

        # assert
        captured = capsys.readouterr()
        assert code == 130
        assert captured.out == "\noperation cancelled\n"
        assert captured.err == ""

    def test_root_refusal_emits_the_envelope_under_json(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act — euid 0 outside a container, but --json asked for a payload
        code = run(
            ["usage", "work", "--json"],
            _use_cases(tmp_path),
            process=ProcessContext(euid=0, in_container=False),
        )

        # assert
        captured = capsys.readouterr()
        assert code == 1
        assert captured.err == ""
        assert json.loads(captured.out) == {
            "schemaVersion": 1,
            "error": {
                "type": "RootRefused",
                "message": "refusing to run as root (outside a container)",
            },
        }

    def test_commands_without_a_payload_reject_the_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act / assert — --json only exists on payload-bearing verbs; argparse
        # rejects it on add with its usual exit-2 usage error
        with pytest.raises(SystemExit) as excinfo:
            _run(["add", "work", "--json"], _use_cases(tmp_path))
        assert excinfo.value.code == 2
        assert "unrecognized arguments" in capsys.readouterr().err
