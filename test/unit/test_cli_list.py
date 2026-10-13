"""``cam list`` — the account table and its ``--json`` envelope.

User-facing output is pinned exactly — the printed line *is* the interface
(docs/architecture.md §10), so a drift in wording is a regression, not cosmetic.
"""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from support.cli_rigs import run_cli as _run
from support.in_memory_account_store import InMemoryAccountStore
from support.in_memory_settings import emails_visible_settings
from support.in_memory_usage_cache import InMemoryUsageCache
from support.use_cases import SEEDED_SNAPSHOT, make_account, make_use_cases

from claude_acc_manager.accounts.domain.entities import QuarantineEntry
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.usage.domain.usage_cache_entry import EMPTY_USAGE_CACHE_ENTRY
from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot, UsageWindow

_use_cases = make_use_cases
_account = make_account
_USAGE_SNAPSHOT = SEEDED_SNAPSHOT


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
        code = _run(
            ["list"],
            _use_cases(tmp_path, store=store, settings=emails_visible_settings(tmp_path)),
        )

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
        code = _run(
            ["list"],
            _use_cases(tmp_path, store=store, settings=emails_visible_settings(tmp_path)),
        )

        # assert
        assert code == 0
        assert capsys.readouterr().out == (
            "  work\twork@example.com [quarantined]\n  personal\tpersonal@example.com [disabled]\n"
        )

    def test_emails_drop_entirely_by_default(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — privacy.redactEmails defaults on; omission, not masking
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        store.set_active(AccountName("work"))

        # act
        code = _run(["list"], _use_cases(tmp_path, store=store))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "* work\n"


class TestListJsonCommand:
    """cam list --json — schema-v1 rows carrying cached decision-grade usage.

    Contract: ``usage`` is populated only while the cached
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
