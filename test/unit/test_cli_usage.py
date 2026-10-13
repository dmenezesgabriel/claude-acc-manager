"""``cam usage`` — the fleet-usage table and its ``--json`` envelope.

User-facing output is pinned exactly — the printed line *is* the interface
(docs/architecture.md §10), so a drift in wording is a regression, not cosmetic.
"""

from dataclasses import replace
from pathlib import Path

import pytest
from support.cli_rigs import config_for as _config_for
from support.cli_rigs import run_cli as _run
from support.controllable_clock import ControllableClock
from support.fake_account_dir import FakeAccountDir
from support.fake_active_slot import FakeActiveSlot
from support.fake_claude_contract import FakeClaudeContractProbe
from support.fake_credential_store import FakeCredentialStore
from support.fake_token_refresher import FakeTokenRefresher
from support.fake_usage_api import FakeUsageApi
from support.in_memory_account_store import InMemoryAccountStore
from support.in_memory_usage_cache import InMemoryUsageCache
from support.use_cases import (
    SEEDED_CREDENTIALS,
    SEEDED_SNAPSHOT,
    credentials_for,
    make_account,
    make_fetch_usage,
    make_use_cases,
    stored_credential,
)

from claude_acc_manager.accounts.domain.credential_fields import refresh_token_fingerprint
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.shared.claude_contract import contract_for_version
from claude_acc_manager.usage.application.ports import AnthropicApiError, RefreshedTokens
from claude_acc_manager.usage.application.use_cases.fetch_account_usage import FetchAccountUsage
from claude_acc_manager.usage.domain.usage_cache_entry import EMPTY_USAGE_CACHE_ENTRY
from claude_acc_manager.usage.domain.usage_snapshot import ScopedWindow, UsageSnapshot, UsageWindow

_CREDENTIALS = SEEDED_CREDENTIALS
_USAGE_SNAPSHOT = SEEDED_SNAPSHOT
_use_cases = make_use_cases
_fetch_usage = make_fetch_usage
_account = make_account
_stored_credential = stored_credential
_creds_for = credentials_for


class TestUsageCommand:
    def test_unknown_account_prints_a_named_error_and_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = _run(["usage", "ghost"], _use_cases(tmp_path))

        # assert
        assert code == 1
        assert capsys.readouterr().err == "error: no such account: 'ghost'\n"

    def test_prints_the_fetched_usage(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        snapshot = UsageSnapshot(
            five_hour=UsageWindow(pct=62.0, resets_at=None),
            seven_day=UsageWindow(pct=27.0, resets_at=None),
            scoped=(),
        )
        credentials = FakeCredentialStore(credentials={"work": _stored_credential()})
        fetch_usage = _fetch_usage(
            usage_api=FakeUsageApi(snapshot=snapshot), credentials=credentials
        )

        # act
        code = _run(["usage", "work"], _use_cases(tmp_path, store=store, fetch_usage=fetch_usage))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "five_hour: 62%\nseven_day: 27%\n"

    def test_prints_a_scoped_model_window(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        snapshot = UsageSnapshot(
            five_hour=None, seven_day=None, scoped=(ScopedWindow("Fable", 84.0, None),)
        )
        credentials = FakeCredentialStore(credentials={"work": _stored_credential()})
        fetch_usage = _fetch_usage(
            usage_api=FakeUsageApi(snapshot=snapshot), credentials=credentials
        )

        # act
        code = _run(["usage", "work"], _use_cases(tmp_path, store=store, fetch_usage=fetch_usage))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "Fable: 84%\n"

    def test_prints_a_stale_note_when_serving_last_good(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — a frozen last_good served after a 429
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
        code = _run(["usage", "work"], _use_cases(tmp_path, store=store, fetch_usage=fetch_usage))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "five_hour: 10%\n(stale: http-429)\n"

    def test_reports_unknown_when_nothing_is_known(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — no credential captured, so the fetch has nothing to serve
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        fetch_usage = _fetch_usage(credentials=FakeCredentialStore())

        # act
        code = _run(["usage", "work"], _use_cases(tmp_path, store=store, fetch_usage=fetch_usage))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "usage unknown: no-credential\n"

    def test_the_active_account_is_never_refreshed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — an expired token on the LIVE account must not refresh
        # (ADR-0009: Claude Code owns the active slot's tokens; the live
        # config's accountUuid, not the registry pointer, resolves "active")
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        slot = FakeActiveSlot(credentials=_CREDENTIALS, config=_config_for("acc-x"))
        credentials = FakeCredentialStore(
            credentials={"work": _stored_credential(expires_at_ms=0.0)}
        )
        refresher = FakeTokenRefresher()
        fetch_usage = _fetch_usage(credentials=credentials, refresher=refresher)

        # act
        _run(
            ["usage", "work"],
            _use_cases(tmp_path, store=store, slot=slot, fetch_usage=fetch_usage),
        )

        # assert
        assert refresher.requests == []

    def test_a_pointer_active_but_live_foreign_account_still_refreshes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — the pointer says "work" but the live slot belongs to an
        # unmanaged login: "work" is parked, so its expired token refreshes
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        store.set_active(AccountName("work"))
        slot = FakeActiveSlot(credentials=_CREDENTIALS, config=_config_for("acc-foreign"))
        credentials = FakeCredentialStore(
            credentials={"work": _stored_credential(expires_at_ms=0.0)}
        )
        refresher = FakeTokenRefresher(
            refreshed=RefreshedTokens(
                access_token="at-new", refresh_token="rt-new", expires_in_s=3600.0
            )
        )
        fetch_usage = _fetch_usage(credentials=credentials, refresher=refresher)

        # act
        _run(
            ["usage", "work"],
            _use_cases(tmp_path, store=store, slot=slot, fetch_usage=fetch_usage),
        )

        # assert
        assert refresher.requests == ["rt-old"]

    def test_permanent_auth_error_quarantines_the_dead_lineage(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — the parked account's expired token gets invalid_grant
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        reader = FakeAccountDir()
        parked = {"claudeAiOauth": {"accessToken": "at", "refreshToken": "rt-dead"}}
        reader.put(
            store.account_dir(AccountName("work")),
            credentials=parked,
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
            ["usage", "work"],
            _use_cases(tmp_path, store=store, reader=reader, fetch_usage=fetch_usage),
        )

        # assert — the tombstone binds the dead lineage by refresh-token fingerprint
        assert code == 0
        (entry,) = store.quarantined()
        assert entry.name == "work"
        assert entry.reason == "permanent_auth_error"
        assert entry.refresh_token_fingerprint == refresh_token_fingerprint(parked)
        assert capsys.readouterr().out == (
            "usage unknown: invalid_grant\n"
            "quarantined 'work': the provider permanently rejected its refresh token\n"
        )

    def test_permanent_auth_error_with_no_parked_file_tombstones_unfingerprinted(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — the lineage failed but its parked file is already gone;
        # the tombstone still binds the name with a None fingerprint
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        reader = FakeAccountDir()
        credentials = FakeCredentialStore(
            credentials={"work": _stored_credential(expires_at_ms=0.0)}
        )
        fetch_usage = _fetch_usage(
            credentials=credentials,
            refresher=FakeTokenRefresher(error=AnthropicApiError(400, "invalid_grant")),
        )

        # act
        code = _run(
            ["usage", "work"],
            _use_cases(tmp_path, store=store, reader=reader, fetch_usage=fetch_usage),
        )

        # assert
        assert code == 0
        (entry,) = store.quarantined()
        assert entry.name == "work"
        assert entry.refresh_token_fingerprint is None

    def test_an_inactive_account_refreshes_an_expired_token(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — same expired credential, but the account isn't active
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        credentials = FakeCredentialStore(
            credentials={"work": _stored_credential(expires_at_ms=0.0)}
        )
        refresher = FakeTokenRefresher(
            refreshed=RefreshedTokens(
                access_token="at-new", refresh_token="rt-new", expires_in_s=3600.0
            )
        )
        fetch_usage = _fetch_usage(credentials=credentials, refresher=refresher)

        # act
        _run(["usage", "work"], _use_cases(tmp_path, store=store, fetch_usage=fetch_usage))

        # assert
        assert refresher.requests == ["rt-old"]
