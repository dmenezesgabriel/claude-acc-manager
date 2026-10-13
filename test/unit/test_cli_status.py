"""``cam status`` — the active-login readout and its ``--json`` envelope.

User-facing output is pinned exactly — the printed line *is* the interface
(docs/architecture.md §10), so a drift in wording is a regression, not cosmetic.
"""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from support.cli_rigs import run_cli as _run
from support.fake_active_slot import FakeActiveSlot
from support.in_memory_account_store import InMemoryAccountStore
from support.in_memory_settings import emails_visible_settings
from support.in_memory_usage_cache import InMemoryUsageCache
from support.use_cases import SEEDED_CONFIG, make_account, make_use_cases

from claude_acc_manager.accounts.domain.entities import QuarantineEntry
from claude_acc_manager.usage.domain.usage_cache_entry import EMPTY_USAGE_CACHE_ENTRY
from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot, UsageWindow

_use_cases = make_use_cases
_account = make_account
_CONFIG = SEEDED_CONFIG


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
        code = _run(
            ["status"],
            _use_cases(
                tmp_path,
                store=store,
                slot=slot,
                settings=emails_visible_settings(tmp_path),
            ),
        )

        # assert
        assert code == 0
        assert capsys.readouterr().out == "logged in as user@example.com (managed as 'work')\n"

    def test_unmanaged_login_is_reported_as_such(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        slot = FakeActiveSlot(config=_CONFIG)

        # act
        code = _run(
            ["status"],
            _use_cases(tmp_path, slot=slot, settings=emails_visible_settings(tmp_path)),
        )

        # assert
        assert code == 0
        assert capsys.readouterr().out == "logged in as user@example.com (not managed)\n"

    def test_the_email_drops_by_default(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work", account_uuid="acc-123"))
        slot = FakeActiveSlot(config=_CONFIG)

        # act
        code = _run(["status"], _use_cases(tmp_path, store=store, slot=slot))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "logged in (managed as 'work')\n"


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
