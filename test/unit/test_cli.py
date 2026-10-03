"""Unit tests for the cam CLI (add / remove / list / status).

User-facing output is pinned exactly — the printed line *is* the interface
(docs/architecture.md §10), so a drift in wording is a regression, not cosmetic.
"""

import json
import signal
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from support.controllable_clock import ControllableClock
from support.fake_account_dir import FakeAccountDir
from support.fake_active_slot import FakeActiveSlot
from support.fake_claude_contract import FakeClaudeContractProbe
from support.fake_credential_store import FakeCredentialStore
from support.fake_login_launcher import FakeLoginLauncher
from support.fake_ops_lock import FakeOpsLock
from support.fake_token_refresher import FakeTokenRefresher
from support.fake_usage_api import FakeUsageApi
from support.in_memory_account_store import InMemoryAccountStore
from support.in_memory_auto_state import InMemoryAutoState
from support.in_memory_settings import InMemorySettings
from support.in_memory_usage_cache import InMemoryUsageCache
from support.interrupting_fetch_usage import InterruptingFetchUsage
from support.interrupting_list_accounts import InterruptingListAccounts
from support.use_cases import (
    SEEDED_CONFIG,
    SEEDED_CREDENTIALS,
    SEEDED_SNAPSHOT,
    credentials_for,
    make_account,
    make_fetch_usage,
    make_use_cases,
    stored_credential,
)

from claude_acc_manager.accounts.domain.credential_fields import refresh_token_fingerprint
from claude_acc_manager.accounts.domain.entities import QuarantineEntry
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.auto.application.use_cases.freshen_target import FreshenTarget
from claude_acc_manager.auto.domain.auto_state import AutoState
from claude_acc_manager.cli import ProcessContext, UseCases, run
from claude_acc_manager.settings.domain.settings_spec import setting_spec
from claude_acc_manager.shared.claude_contract import contract_for_version
from claude_acc_manager.usage.application.ports import AnthropicApiError, RefreshedTokens
from claude_acc_manager.usage.application.use_cases.fetch_account_usage import FetchAccountUsage
from claude_acc_manager.usage.domain.oauth_credential import StoredOAuthCredential
from claude_acc_manager.usage.domain.usage_cache_entry import EMPTY_USAGE_CACHE_ENTRY
from claude_acc_manager.usage.domain.usage_snapshot import ScopedWindow, UsageSnapshot, UsageWindow

_CREDENTIALS = SEEDED_CREDENTIALS
_CONFIG = SEEDED_CONFIG
_USAGE_SNAPSHOT = SEEDED_SNAPSHOT
_use_cases = make_use_cases
_fetch_usage = make_fetch_usage
_account = make_account
_creds_for = credentials_for
_stored_credential = stored_credential


def _run(argv: list[str], use_cases: UseCases) -> int:
    """Dispatch under a non-root, non-container process context."""
    return run(argv, use_cases, process=ProcessContext(euid=1000, in_container=False))


def _config_for(account_uuid: str) -> dict[str, object]:
    return {"oauthAccount": {"emailAddress": "user@example.com", "accountUuid": account_uuid}}


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


class TestListCommand:
    def test_empty_store_prints_a_placeholder(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = _run(["list"], _use_cases(tmp_path))

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
        code = _run(["list"], _use_cases(tmp_path, store=store))

        # assert
        assert code == 0
        assert capsys.readouterr().out == (
            "* work\twork@example.com\n  personal\tpersonal@example.com\n"
        )

    def test_marks_disabled_and_quarantined_accounts(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — personal parked by hand; work tombstoned by the provider
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        store.upsert(_account("personal"))
        store.set_enabled(AccountName("personal"), False)
        store.set_quarantined(
            QuarantineEntry("work", "permanent_auth_error", "2026-10-01T00:00:00Z", "sha256:x")
        )

        # act
        code = _run(["list"], _use_cases(tmp_path, store=store))

        # assert
        assert code == 0
        assert capsys.readouterr().out == (
            "  work\twork@example.com [quarantined]\n  personal\tpersonal@example.com [disabled]\n"
        )


class TestListJsonCommand:
    """cam list --json — schema-v1 rows carrying cached decision-grade usage.

    Contract: SL-007 — ``usage`` is populated only while the cached
    measurement is decision-grade (cache_trust.trust_ok); anything older
    demotes to the display-grade ``lastGood*`` fields so scripts can never
    act on stale data.
    """

    def test_empty_store_emits_an_empty_accounts_array(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = _run(["list", "--json"], _use_cases(tmp_path))

        # assert
        captured = capsys.readouterr()
        assert code == 0
        assert captured.err == ""
        assert json.loads(captured.out) == {
            "schemaVersion": 1,
            "active": None,
            "accounts": [],
        }

    def test_rows_carry_identity_flags_and_unavailable_usage(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — work is an org account and active; personal is disabled
        store = InMemoryAccountStore(tmp_path)
        store.upsert(
            replace(
                _account("work"),
                organization_uuid="org-1",
                organization_name="Org Inc",
            )
        )
        store.upsert(_account("personal"))
        store.set_active(AccountName("work"))
        store.set_enabled(AccountName("personal"), False)

        # act
        code = _run(["list", "--json"], _use_cases(tmp_path, store=store))

        # assert — every row carries the full base schema; empty cache → unavailable
        captured = capsys.readouterr()
        assert code == 0
        assert captured.err == ""
        assert json.loads(captured.out) == {
            "schemaVersion": 1,
            "active": "work",
            "accounts": [
                {
                    "name": "work",
                    "email": "work@example.com",
                    "accountUuid": "acc-x",
                    "organizationUuid": "org-1",
                    "organizationName": "Org Inc",
                    "isOrganization": True,
                    "active": True,
                    "enabled": True,
                    "quarantined": False,
                    "usageStatus": "unavailable",
                    "usage": None,
                },
                {
                    "name": "personal",
                    "email": "personal@example.com",
                    "accountUuid": "acc-x",
                    "organizationUuid": None,
                    "organizationName": None,
                    "isOrganization": False,
                    "active": False,
                    "enabled": False,
                    "quarantined": False,
                    "usageStatus": "unavailable",
                    "usage": None,
                },
            ],
        }

    def test_a_trusted_cached_entry_projects_decision_grade_usage(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — a fresh measurement whose window resets in the future
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                last_good=UsageSnapshot(
                    five_hour=UsageWindow(pct=62.0, resets_at="1970-01-13T00:00:00Z"),
                    seven_day=None,
                    scoped=(),
                ),
                fetched_at_s=999_750.25,
            ),
        )

        # act
        code = _run(["list", "--json"], _use_cases(tmp_path, store=store, usage_cache=cache))

        # assert — ok rows carry the projected snapshot plus freshness fields
        row = json.loads(capsys.readouterr().out)["accounts"][0]
        assert code == 0
        assert row["usageStatus"] == "ok"
        assert row["usage"] == {
            "fiveHour": {"pct": 62.0, "resetsAt": "1970-01-13T00:00:00Z"},
            "scoped": [],
        }
        assert row["usageFetchedAt"] == "1970-01-12T13:42:30Z"
        assert row["usageAgeSeconds"] == 249.8
        assert "lastGoodUsage" not in row
        assert "usageError" not in row

    def test_an_entry_past_the_trust_ceiling_demotes_to_display_grade(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — age 3600.25s > TRUST_MAX_AGE_S (3600s): not decision-grade
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                last_good=_USAGE_SNAPSHOT,
                fetched_at_s=996_399.75,
            ),
        )

        # act
        code = _run(["list", "--json"], _use_cases(tmp_path, store=store, usage_cache=cache))

        # assert
        row = json.loads(capsys.readouterr().out)["accounts"][0]
        assert code == 0
        assert row["usageStatus"] == "unavailable"
        assert row["usage"] is None
        assert row["lastGoodUsage"] == {
            "fiveHour": {"pct": 10.0},
            "scoped": [],
        }
        assert row["lastGoodFetchedAt"] == "1970-01-12T12:46:39Z"
        assert row["lastGoodAgeSeconds"] == 3600.2

    def test_a_last_good_without_a_timestamp_emits_no_last_good_fields(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — a corrupt cache row: usage but no fetch time to anchor it
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(EMPTY_USAGE_CACHE_ENTRY, last_good=_USAGE_SNAPSHOT),
        )

        # act
        code = _run(["list", "--json"], _use_cases(tmp_path, store=store, usage_cache=cache))

        # assert — undated last-good stays invisible rather than guessing an age
        row = json.loads(capsys.readouterr().out)["accounts"][0]
        assert code == 0
        assert row["usageStatus"] == "unavailable"
        assert "lastGoodUsage" not in row
        assert "lastGoodFetchedAt" not in row

    def test_a_past_window_reset_voids_an_otherwise_young_entry(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — fresh (200s) but the binding window already rolled over
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                last_good=UsageSnapshot(
                    five_hour=UsageWindow(pct=62.0, resets_at="1970-01-12T12:00:00Z"),
                    seven_day=None,
                    scoped=(),
                ),
                fetched_at_s=999_800.0,
            ),
        )

        # act
        code = _run(["list", "--json"], _use_cases(tmp_path, store=store, usage_cache=cache))

        # assert — obsolete data demotes even when the age ceiling has not hit
        row = json.loads(capsys.readouterr().out)["accounts"][0]
        assert code == 0
        assert row["usageStatus"] == "unavailable"
        assert row["usage"] is None
        assert row["lastGoodUsage"] == {
            "fiveHour": {"pct": 62.0, "resetsAt": "1970-01-12T12:00:00Z"},
            "scoped": [],
        }

    def test_a_quarantined_row_reads_relogin_required(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — a tombstoned account with an otherwise trusted cache entry
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        store.set_quarantined(
            QuarantineEntry("work", "permanent_auth_error", "2026-10-01T00:00:00Z", "sha256:x")
        )
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                last_good=_USAGE_SNAPSHOT,
                fetched_at_s=999_800.0,
            ),
        )

        # act
        code = _run(["list", "--json"], _use_cases(tmp_path, store=store, usage_cache=cache))

        # assert — the sentinel wins over the cache; last-good stays display-grade
        row = json.loads(capsys.readouterr().out)["accounts"][0]
        assert code == 0
        assert row["quarantined"] is True
        assert row["usageStatus"] == "relogin_required"
        assert row["usage"] is None
        assert row["lastGoodUsage"] == {"fiveHour": {"pct": 10.0}, "scoped": []}
        assert "usageError" not in row

    def test_a_recorded_failure_adds_error_and_retry_while_backing_off(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — stale entry plus a 429-armed backoff still in force
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                last_good=_USAGE_SNAPSHOT,
                fetched_at_s=996_399.0,
                last_error="http-429",
                backoff_until_s=1_000_300.0,
            ),
        )

        # act
        code = _run(["list", "--json"], _use_cases(tmp_path, store=store, usage_cache=cache))

        # assert
        row = json.loads(capsys.readouterr().out)["accounts"][0]
        assert code == 0
        assert row["usageStatus"] == "unavailable"
        assert row["usageError"] == "http-429"
        assert row["usageRetryAt"] == "1970-01-12T13:51:40Z"

    def test_a_lapsed_backoff_keeps_the_error_but_drops_retry_at(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — backoff deadline already passed: the retry hint goes away
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                last_error="network",
                backoff_until_s=999_900.0,
            ),
        )

        # act
        code = _run(["list", "--json"], _use_cases(tmp_path, store=store, usage_cache=cache))

        # assert
        row = json.loads(capsys.readouterr().out)["accounts"][0]
        assert code == 0
        assert row["usageError"] == "network"
        assert "usageRetryAt" not in row


class TestStatusCommand:
    def test_no_login_prints_a_placeholder(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = _run(["status"], _use_cases(tmp_path))

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
        code = _run(["status"], _use_cases(tmp_path, store=store, slot=slot))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "logged in as user@example.com (managed as 'work')\n"

    def test_unmanaged_login_is_reported_as_such(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        slot = FakeActiveSlot(config=_CONFIG)

        # act
        code = _run(["status"], _use_cases(tmp_path, slot=slot))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "logged in as user@example.com (not managed)\n"


class TestStatusJsonCommand:
    """cam status --json — null / unmanaged / managed live login shapes."""

    def test_no_login_emits_null_active(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # act
        code = _run(["status", "--json"], _use_cases(tmp_path))

        # assert — nothing else ships when there is no login to describe
        captured = capsys.readouterr()
        assert code == 0
        assert captured.err == ""
        assert json.loads(captured.out) == {"schemaVersion": 1, "active": None}

    def test_an_unmanaged_login_marks_managed_false_without_usage_keys(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — a live login the registry does not know
        slot = FakeActiveSlot(config=_CONFIG)

        # act
        code = _run(["status", "--json"], _use_cases(tmp_path, slot=slot))

        # assert — identity only; a foreign login has no usage story to tell
        captured = capsys.readouterr()
        assert code == 0
        assert captured.err == ""
        assert json.loads(captured.out) == {
            "schemaVersion": 1,
            "active": {
                "email": "user@example.com",
                "accountUuid": "acc-123",
                "organizationUuid": None,
                "organizationName": None,
                "managed": False,
            },
        }

    def test_a_managed_login_carries_usage_and_the_account_count(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — live slot is the registry's "work"; cache is decision-grade
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work", account_uuid="acc-123"))
        store.upsert(_account("personal"))
        slot = FakeActiveSlot(config=_CONFIG)
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                last_good=UsageSnapshot(
                    five_hour=UsageWindow(pct=62.0, resets_at="1970-01-13T00:00:00Z"),
                    seven_day=None,
                    scoped=(),
                ),
                fetched_at_s=999_750.25,
            ),
        )

        # act
        code = _run(
            ["status", "--json"],
            _use_cases(tmp_path, store=store, slot=slot, usage_cache=cache),
        )

        # assert — the managed object carries the same usage fields as list rows
        captured = capsys.readouterr()
        assert code == 0
        assert captured.err == ""
        assert json.loads(captured.out) == {
            "schemaVersion": 1,
            "active": {
                "email": "user@example.com",
                "accountUuid": "acc-123",
                "organizationUuid": None,
                "organizationName": None,
                "isOrganization": False,
                "managed": True,
                "managedAs": "work",
                "usageStatus": "ok",
                "usage": {
                    "fiveHour": {"pct": 62.0, "resetsAt": "1970-01-13T00:00:00Z"},
                    "scoped": [],
                },
                "usageFetchedAt": "1970-01-12T13:42:30Z",
                "usageAgeSeconds": 249.8,
            },
            "totalManagedAccounts": 2,
        }

    def test_a_managed_org_login_marks_is_organization(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — the live identity carries org fields
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work", account_uuid="acc-123"))
        slot = FakeActiveSlot(
            config={
                "oauthAccount": {
                    "emailAddress": "user@example.com",
                    "accountUuid": "acc-123",
                    "organizationUuid": "org-9",
                    "organizationName": "Org Inc",
                }
            }
        )

        # act
        code = _run(["status", "--json"], _use_cases(tmp_path, store=store, slot=slot))

        # assert
        active = json.loads(capsys.readouterr().out)["active"]
        assert code == 0
        assert active["organizationUuid"] == "org-9"
        assert active["organizationName"] == "Org Inc"
        assert active["isOrganization"] is True

    def test_a_quarantined_active_login_reads_relogin_required(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — the live account's lineage is tombstoned
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work", account_uuid="acc-123"))
        store.set_quarantined(
            QuarantineEntry("work", "permanent_auth_error", "2026-10-01T00:00:00Z", "sha256:x")
        )
        slot = FakeActiveSlot(config=_CONFIG)

        # act
        code = _run(["status", "--json"], _use_cases(tmp_path, store=store, slot=slot))

        # assert
        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload["active"]["managedAs"] == "work"
        assert payload["active"]["usageStatus"] == "relogin_required"
        assert payload["active"]["usage"] is None


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


class TestUsageJsonCommand:
    """cam usage --json — schema-v1 payload, envelope errors, pure stdout.

    Contract: SL-007 — one json.dumps object on stdout carrying
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


class TestArgParsing:
    def test_no_subcommand_prints_usage_to_stderr_and_exits_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = _run([], _use_cases(tmp_path))

        # assert
        assert code == 2
        assert capsys.readouterr().err == (
            "usage: cam [-h]\n"
            "           {add,remove,list,status,usage,switch,disable,enable,auto,"
            "tui,watch,config}\n"
            "           ...\n"
        )

    def test_rejects_a_flag_shaped_account_name(self, tmp_path: Path):
        # act / assert — argparse treats it as an unknown option
        with pytest.raises(SystemExit):
            _run(["add", "--sneaky"], _use_cases(tmp_path))


class TestRootGuard:
    """euid 0 outside a container is refused before dispatch (§8.6).

    The check runs after parsing (so --help still works) and before the
    handler runs (the refusal gates command execution, not the no-command
    usage print).
    """

    def test_root_outside_a_container_is_refused(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = run(
            ["list"],
            _use_cases(tmp_path),
            process=ProcessContext(euid=0, in_container=False),
        )

        # assert
        assert code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == "error: refusing to run as root (outside a container)\n"

    def test_root_inside_a_container_is_allowed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = run(
            ["list"],
            _use_cases(tmp_path),
            process=ProcessContext(euid=0, in_container=True),
        )

        # assert
        assert code == 0
        assert capsys.readouterr().out == "no accounts registered\n"

    def test_no_subcommand_as_root_prints_usage_not_a_refusal(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act — bare cam never dispatches, so the guard doesn't fire
        code = run([], _use_cases(tmp_path), process=ProcessContext(euid=0, in_container=False))

        # assert
        assert code == 2
        assert "usage:" in capsys.readouterr().err


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


class TestHelpText:
    """--help output describes every command; the phrasing is pinned."""

    def _help(self, tmp_path: Path, capsys: pytest.CaptureFixture[str], *argv: str) -> str:
        with pytest.raises(SystemExit):
            _run([*argv, "--help"], _use_cases(tmp_path))
        return capsys.readouterr().out

    def test_top_level_help_lists_the_prog_description_and_commands(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        text = self._help(tmp_path, capsys)

        # assert
        assert text.startswith(
            "usage: cam [-h]\n"
            "           {add,remove,list,status,usage,switch,disable,enable,auto,"
            "tui,watch,config}\n"
            "           ...\n"
        )
        assert "\nmanage Claude Code OAuth accounts\n" in text
        assert "    add                 register an account via an isolated claude login\n" in text
        assert "    remove              unregister an account and delete its login dir\n" in text
        assert "    list                list registered accounts\n" in text
        assert "    status              show the account the live claude slot uses\n" in text
        assert "    disable             hold an account out of automatic switching\n" in text
        assert "    enable              return a disabled account to automatic switching\n" in text
        assert "    usage               show one account's quota usage\n" in text
        assert "    switch              move the live claude login to another account\n" in text
        assert "    auto                auto-switch loop (one tick with --once)\n" in text
        assert "    tui                 interactive quota dashboard\n" in text
        assert "    watch               interactive live monitor\n" in text
        assert "    config              view or edit persisted settings\n" in text

    def test_add_and_remove_help_document_the_name_argument(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act / assert
        for command in ("add", "remove", "disable", "enable"):
            text = self._help(tmp_path, capsys, command)
            assert text.startswith(f"usage: cam {command} [-h] name\n")
            assert "  name        account name\n" in text

    def test_list_help_documents_the_json_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        text = self._help(tmp_path, capsys, "list")

        # assert
        assert text.startswith("usage: cam list [-h] [--json]\n")
        assert "  --json      emit the schema-v1 JSON payload\n" in text

    def test_status_help_documents_the_json_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        text = self._help(tmp_path, capsys, "status")

        # assert
        assert text.startswith("usage: cam status [-h] [--json]\n")
        assert "  --json      emit the schema-v1 JSON payload\n" in text

    def test_usage_help_documents_the_json_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        text = self._help(tmp_path, capsys, "usage")

        # assert
        assert text.startswith("usage: cam usage [-h] [--json] name\n")
        assert "  name        account name\n" in text
        assert "  --json      emit the schema-v1 JSON payload\n" in text

    def test_config_help_lists_every_subcommand(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        text = self._help(tmp_path, capsys, "config")

        # assert
        assert text.startswith("usage: cam config [-h] {list,get,set,unset,path} ...\n")
        assert "    list                show all effective settings\n" in text
        assert "    get                 print one setting's effective value\n" in text
        assert "    set                 validate and persist one setting\n" in text
        assert "    unset               revert one setting to its default\n" in text
        assert "    path                print the settings.json location\n" in text

    def test_config_list_help_documents_the_json_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        text = self._help(tmp_path, capsys, "config", "list")

        # assert
        assert text.startswith("usage: cam config list [-h] [--json]\n")
        assert "  --json      emit the schema-v1 JSON payload\n" in text

    def test_config_get_help_documents_key_and_json(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        text = self._help(tmp_path, capsys, "config", "get")

        # assert
        assert text.startswith("usage: cam config get [-h] [--json] KEY\n")
        assert "  KEY         dotted key, e.g. autoswitch.threshold\n" in text
        assert "  --json      emit the schema-v1 JSON payload\n" in text

    def test_config_set_help_documents_key_and_value(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        text = self._help(tmp_path, capsys, "config", "set")

        # assert
        assert text.startswith("usage: cam config set [-h] KEY VALUE\n")

    def test_config_unset_and_path_help(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # act / assert
        assert self._help(tmp_path, capsys, "config", "unset").startswith(
            "usage: cam config unset [-h] KEY\n"
        )
        assert self._help(tmp_path, capsys, "config", "path").startswith(
            "usage: cam config path [-h]\n"
        )

    def test_auto_help_documents_every_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        text = self._help(tmp_path, capsys, "auto")

        # assert
        assert text.startswith(
            "usage: cam auto [-h] [--once] [--interval SECONDS] [--threshold PCT]\n"
        )
        assert "  --once                evaluate once, maybe switch, and exit" in text
        assert "  --interval SECONDS    poll interval in loop mode\n" in text
        assert "  --threshold PCT       switch when the active's binding window" in text
        assert "  --cooldown SECONDS    minimum time between proactive switches\n" in text
        assert "  --strategy {best,next-available}\n" in text
        assert "target selection strategy\n" in text
        assert (
            "Runs a foreground polling loop; --once evaluates once and reports the "
            "outcome\nin the exit code (0 switched, 1 error, 2 no action, 3 blocked). "
            "Defaults come\nfrom settings.json; flags override them.\n"
        ) in text
        assert "  --dry-run             report decisions without switching" in text
        assert "  --json                emit one JSON event per line\n" in text


def _park(store: InMemoryAccountStore, reader: FakeAccountDir, name: str) -> None:
    """Register *name* with its credential parked in its account dir."""
    store.upsert(_account(name, account_uuid=f"acc-{name}"))
    reader.put(
        store.account_dir(AccountName(name)),
        credentials=_creds_for(name),
        config=_config_for(f"acc-{name}"),
    )


def _cache_usage(cache: InMemoryUsageCache, name: str, pct: float) -> None:
    """Seed one account's cached usage snapshot (pct = percent used)."""
    snapshot = UsageSnapshot(
        five_hour=UsageWindow(pct=pct, resets_at=None), seven_day=None, scoped=()
    )
    cache.save(name, replace(EMPTY_USAGE_CACHE_ENTRY, last_good=snapshot))


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

    def test_best_strategy_picks_the_roomiest_measured_candidate(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — x live at 80% used; y at 90%, z at 30%
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        _park(store, reader, "z")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))
        cache = InMemoryUsageCache()
        _cache_usage(cache, "x", 80.0)
        _cache_usage(cache, "y", 90.0)
        _cache_usage(cache, "z", 30.0)

        # act
        code = _run(
            ["switch", "--strategy", "best"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot, usage_cache=cache),
        )

        # assert
        assert code == 0
        assert capsys.readouterr().out == "switched to 'z' (was 'x')\n"

    def test_next_available_skips_an_exhausted_candidate(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — y is at its limit (0 headroom); z still has room
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        _park(store, reader, "z")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))
        cache = InMemoryUsageCache()
        _cache_usage(cache, "y", 100.0)
        _cache_usage(cache, "z", 30.0)

        # act
        code = _run(
            ["switch", "--strategy", "next-available"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot, usage_cache=cache),
        )

        # assert
        assert code == 0
        assert capsys.readouterr().out == ("switched to 'z' (was 'x')\nskipped 'y': at-limit\n")

    def test_dry_run_reports_the_plan_without_moving_anything(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))

        # act
        code = _run(
            ["switch", "y", "--dry-run"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot),
        )

        # assert — nothing moved
        assert code == 0
        assert capsys.readouterr().out == "dry run: switched to 'y' (was 'x')\n"
        assert slot.read_credentials() == _creds_for("x")
        y_dir = store.account_dir(AccountName("y"))
        assert reader.read_credentials(y_dir) == _creds_for("y")
        active = store.active()
        assert active is not None and active.name.value == "x"

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

    def test_candidates_exhausted_reports_the_stay(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — every candidate measured at its limit
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))
        cache = InMemoryUsageCache()
        _cache_usage(cache, "y", 100.0)

        # act
        code = _run(
            ["switch", "--strategy", "next-available"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot, usage_cache=cache),
        )

        # assert
        assert code == 0
        assert capsys.readouterr().out == (
            "every candidate is at its limit\nskipped 'y': at-limit\n"
        )

    def test_no_valid_target_reports_the_stay(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — x live, the only other account disabled
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        store.set_enabled(AccountName("y"), False)
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))

        # act
        code = _run(["switch"], _use_cases(tmp_path, store=store, reader=reader, slot=slot))

        # assert
        assert code == 0
        assert capsys.readouterr().out == ("no valid switch target\nskipped 'y': disabled\n")

    def test_best_without_a_current_measurement_reports_usage_unavailable(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — the live account was never measured, so no candidate can
        # provably beat it
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))
        cache = InMemoryUsageCache()
        _cache_usage(cache, "y", 10.0)

        # act
        code = _run(
            ["switch", "--strategy", "best"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot, usage_cache=cache),
        )

        # assert
        assert code == 0
        assert capsys.readouterr().out == "usage unknown — cannot rank candidates\n"

    def test_best_when_the_live_account_already_leads_reports_already_best(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — x live at 10% used, y at 90%
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))
        cache = InMemoryUsageCache()
        _cache_usage(cache, "x", 10.0)
        _cache_usage(cache, "y", 90.0)

        # act
        code = _run(
            ["switch", "--strategy", "best"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot, usage_cache=cache),
        )

        # assert
        assert code == 0
        assert capsys.readouterr().out == ("the active account already has the most headroom\n")

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

    def test_dry_run_reports_the_unmanaged_preservation_it_would_make(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — foreign live login; --dry-run must preview the preserve
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        slot = FakeActiveSlot(credentials=_creds_for("foreign"), config=_config_for("acc-foreign"))

        # act
        code = _run(
            ["switch", "x", "--dry-run"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot),
        )

        # assert — no real path exists yet, so the note names the stash dir
        assert code == 0
        assert capsys.readouterr().out == (
            "dry run: switched to 'x' (was an unmanaged login)\n"
            "dry run: the previous unmanaged login was preserved under unclaimed/\n"
        )

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


class TestTuiEntryPoints:
    """`cam tui` / `cam watch` hand off to the TUI runner with a start screen."""

    @staticmethod
    def _capture_run(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
        """Swap the TUI runner for a recorder — the real one owns the terminal."""
        captured: dict[str, object] = {}

        def fake_run(use_cases: UseCases, *, start: str) -> int:
            captured["start"] = start
            captured["use_cases"] = use_cases
            return 0

        import claude_acc_manager.tui

        monkeypatch.setattr(claude_acc_manager.tui, "run", fake_run)
        return captured

    def test_tui_opens_the_dashboard(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        captured = self._capture_run(monkeypatch)
        use_cases = _use_cases(tmp_path)

        code = _run(["tui"], use_cases)

        assert code == 0
        assert captured["start"] == "dashboard"
        assert captured["use_cases"] is use_cases

    def test_watch_opens_the_watch_screen(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        captured = self._capture_run(monkeypatch)
        use_cases = _use_cases(tmp_path)

        code = _run(["watch"], use_cases)

        assert code == 0
        assert captured["start"] == "watch"
        assert captured["use_cases"] is use_cases


class TestConfigCommand:
    """`cam config` — the persisted settings surface (SL-009)."""

    def test_bare_config_lists_all_keys_with_defaults_marked(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange / act
        code = _run(["config"], _use_cases(tmp_path))

        # assert
        out = capsys.readouterr().out
        assert code == 0
        assert "autoswitch.threshold" in out
        assert "90" in out
        assert out.count("(default)") == 5

    def test_list_marks_only_set_keys(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange
        use_cases = _use_cases(tmp_path)
        _run(["config", "set", "autoswitch.threshold", "80"], use_cases)
        capsys.readouterr()

        # act
        code = _run(["config", "list"], use_cases)

        # assert
        out = capsys.readouterr().out
        assert code == 0
        threshold_line = next(
            line for line in out.splitlines() if line.startswith("autoswitch.threshold")
        )
        assert "80" in threshold_line and "(default)" not in threshold_line
        assert out.count("(default)") == 4

    def test_get_prints_the_effective_value(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange / act
        code = _run(["config", "get", "autoswitch.threshold"], _use_cases(tmp_path))

        # assert
        assert code == 0
        assert capsys.readouterr().out.strip() == "90"

    def test_get_json_reports_is_set(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange
        use_cases = _use_cases(tmp_path)
        _run(["config", "set", "autoswitch.threshold", "80"], use_cases)
        capsys.readouterr()

        # act
        code = _run(["config", "get", "--json", "autoswitch.threshold"], use_cases)

        # assert
        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload == {
            "schemaVersion": 1,
            "key": "autoswitch.threshold",
            "value": 80.0,
            "isSet": True,
        }

    def test_list_json_wraps_every_key(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange / act
        code = _run(["config", "list", "--json"], _use_cases(tmp_path))

        # assert
        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload["schemaVersion"] == 1
        assert payload["path"].endswith("settings.json")
        keys = {row["key"] for row in payload["settings"]}
        assert keys == {
            "autoswitch.threshold",
            "autoswitch.intervalSeconds",
            "autoswitch.cooldownSeconds",
            "autoswitch.hysteresisPct",
            "autoswitch.strategy",
        }
        assert all(row["isSet"] is False for row in payload["settings"])
        values = {row["key"]: row["value"] for row in payload["settings"]}
        assert values == {
            "autoswitch.threshold": 90.0,
            "autoswitch.intervalSeconds": 60.0,
            "autoswitch.cooldownSeconds": 300.0,
            "autoswitch.hysteresisPct": 10.0,
            "autoswitch.strategy": "best",
        }

    def test_set_persists_and_confirms(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange
        use_cases = _use_cases(tmp_path)

        # act
        code = _run(["config", "set", "autoswitch.threshold", "80"], use_cases)

        # assert
        assert code == 0
        assert capsys.readouterr().out.strip() == "autoswitch.threshold = 80"
        assert use_cases.load_settings.execute().threshold == 80.0

    def test_set_unknown_key_errors(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange / act
        code = _run(["config", "set", "autoswitch.bogus", "1"], _use_cases(tmp_path))

        # assert
        assert code == 1
        assert "unknown setting" in capsys.readouterr().err

    def test_set_out_of_range_errors(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange / act
        code = _run(["config", "set", "autoswitch.threshold", "999"], _use_cases(tmp_path))

        # assert
        assert code == 1
        assert "between 50 and 99.9" in capsys.readouterr().err

    def test_unset_reverts_to_the_default(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange
        use_cases = _use_cases(tmp_path)
        _run(["config", "set", "autoswitch.threshold", "80"], use_cases)
        capsys.readouterr()

        # act
        code = _run(["config", "unset", "autoswitch.threshold"], use_cases)

        # assert
        assert code == 0
        assert "autoswitch.threshold unset (default: 90)" in capsys.readouterr().out
        assert use_cases.load_settings.execute().threshold == 90.0

    def test_unset_when_not_set_reports_nothing_to_do(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange / act
        code = _run(["config", "unset", "autoswitch.threshold"], _use_cases(tmp_path))

        # assert
        assert code == 0
        assert "is not set; nothing to do" in capsys.readouterr().err

    def test_path_prints_the_settings_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange / act
        code = _run(["config", "path"], _use_cases(tmp_path))

        # assert
        out = capsys.readouterr().out.strip()
        assert code == 0
        assert out.endswith("settings.json")


# -- cam auto -------------------------------------------------------------------

_STAMP = "13:46:40"  # the use-cases rig's pinned clock (epoch 1_000_000)


def _snap_used(
    pct: float, reset_s: float | None = None, seven_pct: float | None = None
) -> UsageSnapshot:
    """A one/two-window snapshot; *reset_s* is an epoch, rendered the API's ISO-Z."""
    return UsageSnapshot(
        five_hour=UsageWindow(
            pct=pct,
            resets_at=(
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(reset_s)) if reset_s else None
            ),
        ),
        seven_day=UsageWindow(pct=seven_pct, resets_at=None) if seven_pct is not None else None,
        scoped=(),
    )


def _auto_credentials(*names: str) -> FakeCredentialStore:
    """Parked credentials whose access tokens are ``at-<name>``."""
    return FakeCredentialStore(
        credentials={
            name: StoredOAuthCredential(
                access_token=f"at-{name}",
                refresh_token=f"rt-{name}",
                expires_at_ms=1e13,
            )
            for name in names
        }
    )


def _auto_rig(
    tmp_path: Path,
    *,
    snaps: dict[str, UsageSnapshot | Exception],
    credentials: FakeCredentialStore | None = None,
    settings: InMemorySettings | None = None,
    auto_state: InMemoryAutoState | None = None,
    freshen_target: FreshenTarget | None = None,
    cache: InMemoryUsageCache | None = None,
    refresher: FakeTokenRefresher | None = None,
    parked: tuple[str, ...] = ("y",),
    clock_s: float = 1_000_000.0,
) -> UseCases:
    """x live plus *parked* accounts — wired for ``cam auto`` dispatches.

    Fresh rows are all due, so the tick fetches everyone: ``snaps`` keys
    are access tokens, and the matching ``at-<name>`` credentials make each
    account read its own scripted value.
    """
    store = InMemoryAccountStore(tmp_path)
    reader = FakeAccountDir()
    _park(store, reader, "x")
    for name in parked:
        _park(store, reader, name)
    reader.delete_credentials(store.account_dir(AccountName("x")))
    store.set_active(AccountName("x"))
    slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))
    resolved_credentials = credentials or FakeCredentialStore()
    resolved_cache = cache or InMemoryUsageCache()
    usage_clock = ControllableClock(now_epoch_s=clock_s)
    fetch = _fetch_usage(
        usage_api=FakeUsageApi(by_token=snaps),
        refresher=refresher,
        credentials=resolved_credentials,
        usage_cache=resolved_cache,
        usage_clock=usage_clock,
    )
    return _use_cases(
        tmp_path,
        store=store,
        reader=reader,
        slot=slot,
        fetch_usage=fetch,
        usage_cache=resolved_cache,
        usage_clock=usage_clock,
        credentials=resolved_credentials,
        settings=settings,
        auto_state=auto_state,
        freshen_target=freshen_target,
    )


def _until(predicate: Callable[[], bool], timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    return predicate()


class TestAutoCommand:
    """``cam auto`` — the engine over the real use cases, fakes at the ports."""

    def test_once_below_threshold_is_no_action(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(50.0), "at-y": _snap_used(20.0)},
            credentials=_auto_credentials("x", "y"),
        )

        # act
        code = _run(["auto", "--once"], use_cases)

        # assert
        assert code == 2
        assert capsys.readouterr().out == (
            f"{_STAMP}  x: 50% used (switch at 90%) | others: y: 5h 20%\n"
            f"{_STAMP}  no switch: below-threshold (50% < 90%)\n"
        )

    def test_once_switches_onto_a_qualifying_candidate(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — x over threshold; y credentialed and roomy
        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(95.0), "at-y": _snap_used(20.0)},
            credentials=_auto_credentials("x", "y"),
        )

        # act
        code = _run(["auto", "--once"], use_cases)

        # assert
        assert code == 0
        assert capsys.readouterr().out == (
            f"{_STAMP}  x: 95% used (switch at 90%) | others: y: 5h 20%\n"
            f"{_STAMP}  Switched x -> y (proactive)\n"
        )
        slot = use_cases.status
        assert slot.execute() is not None and slot.execute().managed_as == "y"

    def test_once_all_exhausted_is_blocked_exit_3(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(100.0), "at-y": _snap_used(100.0)},
            credentials=_auto_credentials("x", "y"),
        )

        # act
        code = _run(["auto", "--once"], use_cases)

        # assert
        assert code == 3
        assert capsys.readouterr().out == (
            f"{_STAMP}  x: 100% used (switch at 90%) | others: y: 5h 100%\n"
            f"{_STAMP}  all accounts exhausted; no reset time known\n"
        )

    def test_once_exhausted_line_names_the_earliest_reset(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — y reports a reset an hour past the pinned clock
        use_cases = _auto_rig(
            tmp_path,
            snaps={
                "at-x": _snap_used(100.0, reset_s=1_007_200.0),
                "at-y": _snap_used(100.0, reset_s=1_003_600.0),
            },
            credentials=_auto_credentials("x", "y"),
        )

        # act
        code = _run(["auto", "--once"], use_cases)

        # assert
        assert code == 3
        assert "all accounts exhausted; earliest reset 1970-01-12T14:46:40Z\n" in (
            capsys.readouterr().out
        )

    def test_once_dry_run_decides_without_mutating(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        auto_state = InMemoryAutoState()
        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(95.0), "at-y": _snap_used(20.0)},
            credentials=_auto_credentials("x", "y"),
            auto_state=auto_state,
        )
        slot_before = use_cases.status.execute()

        # act
        code = _run(["auto", "--once", "--dry-run"], use_cases)

        # assert — would-be switch rendered, nothing moved, nothing recorded
        assert code == 0
        assert "[dry-run] would switch x -> y (proactive)\n" in capsys.readouterr().out
        assert use_cases.status.execute() == slot_before
        assert auto_state.load() == AutoState()
        assert (
            use_cases.account_files.read_credentials(
                use_cases.account_store.account_dir(AccountName("y"))
            )
            is not None
        )

    def test_once_json_emits_one_event_object_per_line(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(100.0), "at-y": _snap_used(100.0)},
            credentials=_auto_credentials("x", "y"),
        )

        # act
        code = _run(["auto", "--once", "--json"], use_cases)

        # assert — JSONL: every line is its own object; the exit still codes
        assert code == 3
        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert [line["event"] for line in lines] == ["poll", "all-exhausted"]
        assert all(line["schemaVersion"] == 1 and line["ts"] for line in lines)
        assert lines[0]["active"] == "x"
        assert lines[0]["headroomPct"] == {"x": 0.0, "y": 0.0}
        assert lines[0]["threshold"] == 90
        assert lines[0]["windowsPct"] == {"x": {"5h": 100.0}, "y": {"5h": 100.0}}
        assert lines[1]["earliestResetAt"] is None

    def test_once_json_reports_the_earliest_reset(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — every account maxed; x's window resets first
        use_cases = _auto_rig(
            tmp_path,
            snaps={
                "at-x": _snap_used(100.0, 1_003_600.0),
                "at-y": _snap_used(100.0, 1_007_200.0),
            },
            credentials=_auto_credentials("x", "y"),
        )

        # act
        code = _run(["auto", "--once", "--json"], use_cases)

        # assert — the earliest reset rides the all-exhausted payload
        assert code == 3
        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert lines[1]["event"] == "all-exhausted"
        assert lines[1]["earliestResetAt"] == "1970-01-12T14:46:40Z"

    def test_once_honors_a_persisted_threshold(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — 85% sits under the 90 default but over the stored 80
        settings = InMemorySettings(tmp_path)
        settings.set_value(setting_spec("autoswitch.threshold"), 80.0)
        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(85.0), "at-y": _snap_used(20.0)},
            credentials=_auto_credentials("x", "y"),
            settings=settings,
        )

        # act
        code = _run(["auto", "--once"], use_cases)

        # assert
        assert code == 0
        assert "switch at 80%" in capsys.readouterr().out

    def test_once_threshold_flag_overrides_settings(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — the flag, not the file, binds this tick
        settings = InMemorySettings(tmp_path)
        settings.set_value(setting_spec("autoswitch.threshold"), 95.0)
        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(85.0), "at-y": _snap_used(20.0)},
            credentials=_auto_credentials("x", "y"),
            settings=settings,
        )

        # act
        code = _run(["auto", "--once", "--threshold", "80"], use_cases)

        # assert
        assert code == 0
        assert "switch at 80%" in capsys.readouterr().out

    def test_once_cooldown_flag_releases_the_hold(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — a switch 100s ago; the default 300s cooldown holds it
        state = AutoState(last_switch_at_s=999_900.0, last_switch_from="x", last_switch_to="y")
        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(95.0), "at-y": _snap_used(20.0)},
            credentials=_auto_credentials("x", "y"),
            auto_state=InMemoryAutoState(state),
        )

        # act / assert — default cooldown blocks; --cooldown 1 releases
        assert _run(["auto", "--once"], use_cases) == 2
        assert f"{_STAMP}  no switch: cooldown\n" in capsys.readouterr().out
        assert _run(["auto", "--once", "--cooldown", "1"], use_cases) == 0

    def test_once_flag_out_of_range_fails_loudly(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = _run(
            ["auto", "--once", "--threshold", "999"],
            _auto_rig(tmp_path, snaps={}),
        )

        # assert — the strict overlay speaks, not a silent clamp
        assert code == 1
        assert "between 50 and 99.9" in capsys.readouterr().err

    def test_once_logged_out_is_no_action(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # act — the default rig has a parked account but no live slot
        code = _run(["auto", "--once"], _use_cases(tmp_path))

        # assert
        assert code == 2
        assert capsys.readouterr().out == (
            f"{_STAMP}  poll: no active account\n"
            f"{_STAMP}  no switch: no-active-account (log in and run 'cam add' first)\n"
        )

    def test_once_a_port_failure_is_error_exit_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — the state port dies inside the tick's never-raises net
        class _RaisingAutoState(InMemoryAutoState):
            def load(self) -> AutoState:
                raise RuntimeError("boom")

        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(50.0)},
            credentials=_auto_credentials("x"),
            auto_state=_RaisingAutoState(),
        )

        # act
        code = _run(["auto", "--once"], use_cases)

        # assert
        assert code == 1
        assert f"{_STAMP}  error: RuntimeError: boom (will retry)\n" in (capsys.readouterr().out)

    def test_once_does_not_install_a_signal_handler(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # arrange
        installed: dict[int, object] = {}
        monkeypatch.setattr(
            signal, "signal", lambda sig, handler: installed.setdefault(sig, handler)
        )
        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(50.0)},
            credentials=_auto_credentials("x"),
        )

        # act
        code = _run(["auto", "--once"], use_cases)

        # assert — signal wiring is loop-mode only
        assert code == 2
        assert installed == {}

    def test_loop_sigterm_stops_the_loop_cleanly(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ):
        # arrange — capture the handler cmd_auto installs instead of signaling;
        # the exhausted scenario lands the loop in its long-sleep branch
        installed: dict[int, object] = {}
        monkeypatch.setattr(
            signal, "signal", lambda sig, handler: installed.setdefault(sig, handler)
        )
        reset = 1_000_270.66  # sleep 330.66s: disambiguates /60 (5.5→"6m")
        use_cases = _auto_rig(
            tmp_path,
            snaps={
                "at-x": _snap_used(100.0, reset_s=reset),
                "at-y": _snap_used(100.0, reset_s=reset),
            },
            credentials=_auto_credentials("x", "y"),
        )
        box: dict[str, int] = {}
        thread = threading.Thread(
            target=lambda: box.setdefault("code", _run(["auto"], use_cases)),
            daemon=True,
        )

        # act — let the first tick land, then deliver the signal
        thread.start()
        assert _until(lambda: installed)
        time.sleep(0.3)
        installed[signal.SIGTERM](signal.SIGTERM, None)
        thread.join(timeout=5.0)

        # assert — a tick ran, the MAX_SLEEP-capped sleep was interrupted
        assert not thread.is_alive()
        assert box["code"] == 0
        out = capsys.readouterr().out
        assert out.startswith("auto-switch running: threshold 90%, every 60s — Ctrl-C to stop\n")
        assert f"{_STAMP}  sleeping 6m (until 1970-01-12T13:52:10Z)\n" in out

    def test_loop_json_suppresses_the_banner(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ):
        # arrange — the exhausted scenario also lands the sleep event in JSONL;
        # the fractional clock makes `seconds` non-integral, so `round()`
        # mutants (None/0/2 digits) can't smuggle the same value through
        installed: dict[int, object] = {}
        monkeypatch.setattr(
            signal, "signal", lambda sig, handler: installed.setdefault(sig, handler)
        )
        reset = 1_000_270.0
        use_cases = _auto_rig(
            tmp_path,
            snaps={
                "at-x": _snap_used(100.0, reset_s=reset),
                "at-y": _snap_used(100.0, reset_s=reset),
            },
            credentials=_auto_credentials("x", "y"),
            clock_s=1_000_000.54,
        )
        thread = threading.Thread(target=lambda: _run(["auto", "--json"], use_cases), daemon=True)

        # act
        thread.start()
        assert _until(lambda: installed)
        time.sleep(0.3)
        installed[signal.SIGTERM](signal.SIGTERM, None)
        thread.join(timeout=5.0)

        # assert — JSONL purity: no banner, every line is its own event object
        assert not thread.is_alive()
        out = capsys.readouterr().out
        assert "auto-switch running" not in out
        lines = [json.loads(line) for line in out.splitlines()]
        assert [line["event"] for line in lines] == ["poll", "all-exhausted", "sleep"]
        assert '"seconds": 329.5' in out
        assert lines[2]["until"] == "1970-01-12T13:52:10Z"

    def test_once_quarantines_a_dead_lineage(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — y's parked refresh grant is provably dead
        use_cases = _dead_lineage_rig(tmp_path)

        # act
        code = _run(["auto", "--once"], use_cases)

        # assert — the lineage is tombstoned and the tick reports BLOCKED
        assert code == 3
        assert capsys.readouterr().out == (
            f"{_STAMP}  x: 95% used (switch at 90%) | others: y: 5h 20%\n"
            f"{_STAMP}  y quarantined: invalid_grant. "
            "Log in with it and run 'cam add y' to recover.\n"
            f"{_STAMP}  no switch: no-viable-target\n"
        )
        (entry,) = use_cases.account_store.quarantined()
        assert entry.name == "y"
        assert entry.reason == "permanent_auth_error"

    def test_once_json_marks_a_dead_lineage(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — a second rig: quarantine persists and would skew a rerun
        use_cases = _dead_lineage_rig(tmp_path)

        # act
        code = _run(["auto", "--once", "--json"], use_cases)

        # assert
        assert code == 3
        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert [line["event"] for line in lines] == [
            "poll",
            "account-quarantined",
            "no-switch",
        ]
        assert lines[1]["name"] == "y"
        assert lines[1]["reason"] == "invalid_grant"
        assert lines[2]["reason"] == "no-viable-target"

    def test_once_json_renders_a_switch(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange
        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(95.0), "at-y": _snap_used(20.0)},
            credentials=_auto_credentials("x", "y"),
        )

        # act
        code = _run(["auto", "--once", "--json"], use_cases)

        # assert
        assert code == 0
        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert lines[1]["event"] == "switch"
        assert lines[1]["trigger"] == "proactive"
        assert lines[1]["from"] == "x" and lines[1]["to"] == "y"
        assert lines[1]["dryRun"] is False

    def test_once_json_renders_an_error(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange — the state port dies inside the tick's never-raises net
        class _RaisingAutoState(InMemoryAutoState):
            def load(self) -> AutoState:
                raise RuntimeError("boom")

        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(50.0)},
            credentials=_auto_credentials("x"),
            auto_state=_RaisingAutoState(),
        )

        # act
        code = _run(["auto", "--once", "--json"], use_cases)

        # assert
        assert code == 1
        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert lines[-1]["event"] == "error"
        assert lines[-1]["message"] == "RuntimeError: boom"
        assert lines[-1]["transient"] is True

    def test_once_json_logged_out_reports_null_active(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = _run(["auto", "--once", "--json"], _use_cases(tmp_path))

        # assert
        assert code == 2
        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert [line["event"] for line in lines] == ["poll", "no-switch"]
        assert lines[0]["active"] is None
        assert lines[1]["reason"] == "no-active-account"
        assert lines[1]["detail"] == "log in and run 'cam add' first"

    def test_once_reports_fetch_errors_in_the_census(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — every poll fails; headroom is unmeasurable
        use_cases = _auto_rig(
            tmp_path,
            snaps={
                "at-x": AnthropicApiError(429, "rate_limit_error"),
                "at-y": AnthropicApiError(500, "api_error"),
            },
            credentials=_auto_credentials("x", "y"),
        )

        # act
        code = _run(["auto", "--once"], use_cases)

        # assert — the census explains itself; unknown active usage can't act
        assert code == 2
        assert capsys.readouterr().out == (
            f"{_STAMP}  x: usage unknown (http-429) (switch at 90%) | others: y: ? (http-500)\n"
            f"{_STAMP}  no switch: active-usage-unknown\n"
        )

        # act — JSONL names the same causes on a fresh rig (backoff arms after
        # the first tick and would change the wording on a rerun)
        json_rig = _auto_rig(
            tmp_path,
            snaps={
                "at-x": AnthropicApiError(429, "rate_limit_error"),
                "at-y": AnthropicApiError(500, "api_error"),
            },
            credentials=_auto_credentials("x", "y"),
        )
        assert _run(["auto", "--once", "--json"], json_rig) == 2

        # assert
        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert lines[0]["fetchErrors"] == {"x": "http-429", "y": "http-500"}

    def test_once_renders_a_never_polled_parked_account(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — y's row is not due (a far deadline would oversleep and
        # re-enter the plan) and holds nothing yet: a bare "?"
        cache = InMemoryUsageCache()
        cache.save(
            "y",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                fetched_at_s=999_000.0,
                next_poll_at_s=1_000_300.0,
            ),
        )
        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(50.0)},
            credentials=_auto_credentials("x"),
            cache=cache,
        )

        # act
        code = _run(["auto", "--once"], use_cases)

        # assert
        assert code == 2
        assert capsys.readouterr().out == (
            f"{_STAMP}  x: 50% used (switch at 90%) | others: y: ?\n"
            f"{_STAMP}  no switch: below-threshold (50% < 90%)\n"
        )

    def test_once_renders_unknown_active_usage_without_a_cause(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — x's row was fetched recently and its plan is not due, so
        # the tick skips it entirely; with no candidates there is nothing to
        # escalate either: bare "usage unknown", no recorded cause
        cache = InMemoryUsageCache()
        cache.save(
            "x",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                fetched_at_s=1_000_000.0,
                next_poll_at_s=1_000_300.0,
            ),
        )
        use_cases = _auto_rig(
            tmp_path,
            snaps={},
            credentials=_auto_credentials("x"),
            cache=cache,
            parked=(),
        )

        # act
        code = _run(["auto", "--once"], use_cases)

        # assert
        assert code == 2
        assert capsys.readouterr().out == (
            f"{_STAMP}  x: usage unknown (switch at 90%)\n"
            f"{_STAMP}  no switch: active-usage-unknown\n"
        )

    def test_once_joins_multi_window_and_multi_account_rows(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — two parked accounts; the poll picks one, so z stays "?"
        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(50.0), "at-y": _snap_used(50.0, seven_pct=40.0)},
            credentials=_auto_credentials("x", "y"),
            parked=("y", "z"),
        )

        # act
        code = _run(["auto", "--once"], use_cases)

        # assert — the census joins windows with " · " and accounts with ", "
        assert code == 2
        assert capsys.readouterr().out == (
            f"{_STAMP}  x: 50% used (switch at 90%) | others: y: 5h 50% · 7d 40%, z: ?\n"
            f"{_STAMP}  no switch: below-threshold (50% < 90%)\n"
        )

    def test_once_best_strategy_prefers_the_roomiest_candidate(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — z holds more headroom than y; only "best" reaches it
        use_cases = _auto_rig(
            tmp_path,
            snaps={
                "at-x": _snap_used(95.0),
                "at-y": _snap_used(50.0),
                "at-z": _snap_used(20.0),
            },
            credentials=_auto_credentials("x", "y", "z"),
            parked=("y", "z"),
        )

        # act
        code = _run(["auto", "--once", "--strategy", "best"], use_cases)

        # assert
        assert code == 0
        assert f"{_STAMP}  Switched x -> z (proactive)\n" in capsys.readouterr().out

    def test_once_next_available_takes_the_first_eligible(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — same rig as "best"; the flag changes the pick to y
        use_cases = _auto_rig(
            tmp_path,
            snaps={
                "at-x": _snap_used(95.0),
                "at-y": _snap_used(50.0),
                "at-z": _snap_used(20.0),
            },
            credentials=_auto_credentials("x", "y", "z"),
            parked=("y", "z"),
        )

        # act
        code = _run(["auto", "--once", "--strategy", "next-available"], use_cases)

        # assert
        assert code == 0
        assert f"{_STAMP}  Switched x -> y (proactive)\n" in capsys.readouterr().out

    def test_loop_banner_echoes_interval_and_dry_run(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ):
        # arrange
        installed: dict[int, object] = {}
        monkeypatch.setattr(
            signal, "signal", lambda sig, handler: installed.setdefault(sig, handler)
        )
        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(50.0)},
            credentials=_auto_credentials("x"),
        )
        thread = threading.Thread(
            target=lambda: _run(["auto", "--interval", "15", "--dry-run"], use_cases),
            daemon=True,
        )

        # act
        thread.start()
        assert _until(lambda: installed)
        time.sleep(0.3)
        installed[signal.SIGTERM](signal.SIGTERM, None)
        thread.join(timeout=5.0)

        # assert — the flag values reach the banner verbatim
        assert not thread.is_alive()
        out = capsys.readouterr().out
        assert out.startswith(
            "auto-switch running: threshold 90%, every 15s (dry-run) — Ctrl-C to stop\n"
        )

    def test_emit_flushes_every_printed_line(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — JSONL is a stream contract: every print must flush
        kwargs_log: list[dict[str, object]] = []
        real_print = print
        monkeypatch.setattr(
            "builtins.print",
            lambda *a, **kw: (kwargs_log.append(dict(kw)), real_print(*a, **kw)),
        )
        rig = lambda: _auto_rig(  # noqa: E731 — test-local scenario factory
            tmp_path,
            snaps={"at-x": _snap_used(50.0)},
            credentials=_auto_credentials("x"),
        )

        # act — one human run, one JSONL run (fresh rigs)
        assert _run(["auto", "--once"], rig()) == 2
        assert _run(["auto", "--once", "--json"], rig()) == 2

        # assert
        assert kwargs_log
        assert all(kw.get("flush") is True for kw in kwargs_log)


def _dead_lineage_rig(tmp_path: Path) -> UseCases:
    """x live at 95%; y parked with an expired grant the fresher rejects.

    x inside the escalation band force-refreshes y: the poll's own grant
    succeeds but writes a zero-lifetime rotation, so y is still expired
    when *freshen* runs and *its* grant returns ``invalid_grant`` — dead.
    """
    credentials = FakeCredentialStore(
        credentials={
            "x": StoredOAuthCredential("at-x", "rt-x", 1e13),
            "y": StoredOAuthCredential("at-y", "rt-y", 0.0),
        }
    )
    return _auto_rig(
        tmp_path,
        snaps={"at-x": _snap_used(95.0), "at-y2": _snap_used(20.0)},
        credentials=credentials,
        refresher=FakeTokenRefresher(refreshed=RefreshedTokens("at-y2", "rt-y2", expires_in_s=0.0)),
        freshen_target=FreshenTarget(
            FakeTokenRefresher(error=AnthropicApiError(400, "invalid_grant")),
            credentials,
            ControllableClock(now_epoch_s=1_000_000.0),
            FakeClaudeContractProbe(contract_for_version((2, 1, 288))),
        ),
    )
