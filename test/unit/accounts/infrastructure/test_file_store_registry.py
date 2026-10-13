"""``FileAccountStore`` registry document — schema and validation messages.

A malformed ``registry.json`` must fail loudly with a message that names the
offending field; these tests pin both the schema and the wording.
"""

import json
from pathlib import Path

import pytest
from support.file_store_rigs import make_account, make_store, registry_doc, write_registry

from claude_acc_manager.accounts.infrastructure.file_account_store import (
    FileAccountStore,
)


class TestRegistryValidationMessages:
    """Malformed registries fail with exact, user-facing messages (the CLI's
    diagnostic surface; every literal is pinned, mutation-tested)."""

    @staticmethod
    def assert_message(store_root: Path, document: object, expected: str) -> None:
        # arrange
        write_registry(store_root, document)  # type: ignore[arg-type]
        store = FileAccountStore(store_root=store_root)

        # act
        with pytest.raises(ValueError) as raised:
            store.list_accounts()

        # assert
        assert str(raised.value) == expected

    def test_document_not_an_object(self, tmp_path: Path):
        self.assert_message(tmp_path / "store", [], "registry must be a JSON object, got []")

    def test_unknown_top_level_field(self, tmp_path: Path):
        self.assert_message(
            tmp_path / "store",
            {
                "schemaVersion": 1,
                "order": [],
                "active": None,
                "accounts": {},
                "quarantined": [],
                "surprise": True,
            },
            "registry has unknown top-level fields ['surprise']",
        )

    def test_missing_top_level_field(self, tmp_path: Path):
        self.assert_message(
            tmp_path / "store",
            {"schemaVersion": 1, "order": [], "active": None, "accounts": {}},
            "registry is missing top-level fields ['quarantined']",
        )

    def test_unsupported_schema_version(self, tmp_path: Path):
        self.assert_message(
            tmp_path / "store",
            {
                "schemaVersion": 99,
                "order": [],
                "active": None,
                "accounts": {},
                "quarantined": [],
            },
            "registry schemaVersion 99 is not supported (expected 1)",
        )

    def test_boolean_schema_version_is_rejected(self, tmp_path: Path):
        # arrange — bool is a subclass of int (True == 1), so a bare
        # isinstance(int) check alone would let it pass as schema version 1
        self.assert_message(
            tmp_path / "store",
            {
                "schemaVersion": True,
                "order": [],
                "active": None,
                "accounts": {},
                "quarantined": [],
            },
            "registry schemaVersion True is not supported (expected 1)",
        )

    def test_accounts_not_an_object(self, tmp_path: Path):
        self.assert_message(
            tmp_path / "store",
            {
                "schemaVersion": 1,
                "order": [],
                "active": None,
                "accounts": [],
                "quarantined": [],
            },
            "registry accounts must be a JSON object, got []",
        )

    def test_order_not_a_list(self, tmp_path: Path):
        self.assert_message(
            tmp_path / "store",
            {
                "schemaVersion": 1,
                "order": "work",
                "active": None,
                "accounts": {},
                "quarantined": [],
            },
            "registry order must be a list of names, got 'work'",
        )

    def test_order_with_a_non_name_element(self, tmp_path: Path):
        self.assert_message(
            tmp_path / "store",
            {
                "schemaVersion": 1,
                "order": ["work", 42],
                "active": None,
                "accounts": {"work": {}},
                "quarantined": [],
            },
            "registry order must be a list of names, got ['work', 42]",
        )

    def test_active_not_a_name_or_null(self, tmp_path: Path):
        self.assert_message(
            tmp_path / "store",
            {
                "schemaVersion": 1,
                "order": [],
                "active": 42,
                "accounts": {},
                "quarantined": [],
            },
            "registry active must be a name or null, got 42",
        )

    def test_quarantined_not_a_list(self, tmp_path: Path):
        self.assert_message(
            tmp_path / "store",
            {
                "schemaVersion": 1,
                "order": [],
                "active": None,
                "accounts": {},
                "quarantined": "none",
            },
            "registry quarantined must be a list, got 'none'",
        )

    def test_order_references_unknown_account(self, tmp_path: Path):
        self.assert_message(
            tmp_path / "store",
            {
                "schemaVersion": 1,
                "order": ["ghost"],
                "active": None,
                "accounts": {},
                "quarantined": [],
            },
            "registry order references unknown account 'ghost'",
        )

    def test_record_not_an_object(self, tmp_path: Path):
        self.assert_message(
            tmp_path / "store",
            {
                "schemaVersion": 1,
                "order": [],
                "active": None,
                "accounts": {"work": []},
                "quarantined": [],
            },
            "registry record 'work' must be a JSON object, got []",
        )

    def test_record_unknown_field(self, tmp_path: Path):
        self.assert_message(
            tmp_path / "store",
            {
                "schemaVersion": 1,
                "order": [],
                "active": None,
                "accounts": {"work": {"surprise": True}},
                "quarantined": [],
            },
            "registry record 'work' has unknown fields ['surprise']",
        )

    def test_record_missing_field(self, tmp_path: Path):
        self.assert_message(
            tmp_path / "store",
            {
                "schemaVersion": 1,
                "order": [],
                "active": None,
                "accounts": {"work": {"email": "user@example.com"}},
                "quarantined": [],
            },
            "registry record 'work' is missing fields"
            " ['account_uuid', 'organization_uuid', 'organization_name',"
            " 'added_at', 'enabled']",
        )

    @staticmethod
    def complete_record(**overrides: object) -> dict[str, object]:
        record: dict[str, object] = {
            "email": "user@example.com",
            "account_uuid": "acc-uuid-1",
            "organization_uuid": None,
            "organization_name": None,
            "added_at": "2026-09-10T12:00:00Z",
            "enabled": True,
        }
        record.update(overrides)
        return record

    def test_record_enabled_not_a_bool(self, tmp_path: Path):
        self.assert_message(
            tmp_path / "store",
            {
                "schemaVersion": 1,
                "order": [],
                "active": None,
                "accounts": {"work": self.complete_record(enabled="yes")},
                "quarantined": [],
            },
            "registry record 'work': enabled must be a bool, got 'yes'",
        )

    def test_record_email_not_a_str(self, tmp_path: Path):
        self.assert_message(
            tmp_path / "store",
            {
                "schemaVersion": 1,
                "order": [],
                "active": None,
                "accounts": {"work": self.complete_record(email=42)},
                "quarantined": [],
            },
            "registry record 'work': email must be a str, got 42",
        )

    def test_record_account_uuid_not_a_str(self, tmp_path: Path):
        self.assert_message(
            tmp_path / "store",
            {
                "schemaVersion": 1,
                "order": [],
                "active": None,
                "accounts": {"work": self.complete_record(account_uuid=42)},
                "quarantined": [],
            },
            "registry record 'work': account_uuid must be a str, got 42",
        )

    def test_record_added_at_not_a_str(self, tmp_path: Path):
        self.assert_message(
            tmp_path / "store",
            {
                "schemaVersion": 1,
                "order": [],
                "active": None,
                "accounts": {"work": self.complete_record(added_at=42)},
                "quarantined": [],
            },
            "registry record 'work': added_at must be a str, got 42",
        )

    def test_record_organization_uuid_not_a_str_or_null(self, tmp_path: Path):
        self.assert_message(
            tmp_path / "store",
            {
                "schemaVersion": 1,
                "order": [],
                "active": None,
                "accounts": {"work": self.complete_record(organization_uuid=42)},
                "quarantined": [],
            },
            "registry record 'work': organization_uuid must be a str or null, got 42",
        )

    def test_record_organization_name_not_a_str_or_null(self, tmp_path: Path):
        self.assert_message(
            tmp_path / "store",
            {
                "schemaVersion": 1,
                "order": [],
                "active": None,
                "accounts": {"work": self.complete_record(organization_name=42)},
                "quarantined": [],
            },
            "registry record 'work': organization_name must be a str or null, got 42",
        )


class TestRegistrySchema:
    """registry.json v1: schemaVersion, order, active, accounts, quarantined."""

    def test_document_has_the_locked_top_level_keys(self, tmp_path: Path):
        # arrange
        store = make_store(tmp_path)

        # act
        store.upsert(make_account("work"))

        # assert
        document = registry_doc(tmp_path / "store")
        assert set(document.keys()) == {
            "schemaVersion",
            "order",
            "active",
            "accounts",
            "quarantined",
        }
        assert document["schemaVersion"] == 1
        assert document["order"] == ["work"]
        assert document["active"] is None
        assert document["quarantined"] == []

    def test_missing_registry_is_an_empty_store(self, tmp_path: Path):
        # arrange
        store = make_store(tmp_path)

        # act / assert
        assert store.list_accounts() == []
        assert store.active() is None

    def test_corrupt_registry_fails_loudly(self, tmp_path: Path):
        # arrange — our own file: no salvage (salvage is for claude-code's
        # files, docs/architecture.md §10); the JSON error surfaces as-is
        store = make_store(tmp_path)
        (tmp_path / "store").mkdir()
        (tmp_path / "store" / "registry.json").write_text("{broken", encoding="utf-8")

        # act / assert
        with pytest.raises(json.JSONDecodeError):
            store.list_accounts()

    def test_unknown_registry_field_raises(self, tmp_path: Path):
        # arrange — schema drift is surfaced, not swallowed (docs/architecture.md §11)
        store = make_store(tmp_path)
        write_registry(
            tmp_path / "store",
            {
                "schemaVersion": 1,
                "order": [],
                "active": None,
                "accounts": {},
                "quarantined": [],
                "surprise": True,
            },
        )

        # act / assert
        with pytest.raises(ValueError, match="surprise"):
            store.list_accounts()

    def test_wrong_schema_version_raises(self, tmp_path: Path):
        # arrange
        store = make_store(tmp_path)
        document = {
            "schemaVersion": 99,
            "order": [],
            "active": None,
            "accounts": {},
            "quarantined": [],
        }
        write_registry(tmp_path / "store", document)

        # act / assert
        with pytest.raises(ValueError, match="99"):
            store.list_accounts()

    def test_order_references_unknown_account(self, tmp_path: Path):
        # arrange — torn state must not crash reads with a KeyError out of
        # nowhere; unknown order entries are reported as corruption
        store = make_store(tmp_path)
        write_registry(
            tmp_path / "store",
            {
                "schemaVersion": 1,
                "order": ["ghost"],
                "active": None,
                "accounts": {},
                "quarantined": [],
            },
        )

        # act / assert
        with pytest.raises(ValueError, match="ghost"):
            store.list_accounts()
