"""``FileAccountStore`` quarantine — tombstoned accounts and their validation."""

from pathlib import Path

import pytest
from support.file_store_rigs import (
    make_account,
    make_store,
    registry_doc,
    write_registry,
)
from support.file_store_rigs import (
    quarantine_entry as _quarantine_entry,
)

from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.accounts.infrastructure.file_account_store import (
    FileAccountStore,
)


class TestQuarantine:
    """quarantined[] records dead lineages; keyed by name, durable."""

    def test_empty_store_has_no_entries(self, tmp_path: Path):
        # arrange / act / assert
        assert make_store(tmp_path).quarantined() == []

    def test_set_quarantined_persists_the_entry(self, tmp_path: Path):
        # arrange
        store = make_store(tmp_path)
        store.upsert(make_account("work"))

        # act
        store.set_quarantined(_quarantine_entry("work"))

        # assert — the registry file carries it (durable across processes)
        assert store.quarantined() == [_quarantine_entry("work")]
        assert registry_doc(tmp_path / "store")["quarantined"] == [
            {
                "name": "work",
                "reason": "permanent_auth_error",
                "at": "2026-09-10T12:00:00Z",
                "refresh_token_fingerprint": "sha256:dead",
            }
        ]

    def test_set_quarantined_on_unknown_account_raises(self, tmp_path: Path):
        # arrange — a quarantine entry names a registered lineage; a ghost
        # name is a bug, not data (same KeyError contract as set_enabled)
        store = make_store(tmp_path)

        # act / assert
        with pytest.raises(KeyError, match="ghost"):
            store.set_quarantined(_quarantine_entry("ghost"))

    def test_re_quarantining_replaces_the_entry(self, tmp_path: Path):
        # arrange — a second invalid_grant updates the recorded lineage
        store = make_store(tmp_path)
        store.upsert(make_account("work"))
        store.set_quarantined(_quarantine_entry("work"))

        # act
        store.set_quarantined(_quarantine_entry("work", refresh_token_fingerprint="sha256:newer"))

        # assert — one entry per name, latest wins
        assert store.quarantined() == [
            _quarantine_entry("work", refresh_token_fingerprint="sha256:newer")
        ]

    def test_clear_quarantined_drops_the_entry(self, tmp_path: Path):
        # arrange
        store = make_store(tmp_path)
        store.upsert(make_account("work"))
        store.set_quarantined(_quarantine_entry("work"))

        # act
        store.clear_quarantined(AccountName("work"))

        # assert
        assert store.quarantined() == []
        assert registry_doc(tmp_path / "store")["quarantined"] == []

    def test_clear_quarantined_is_a_noop_when_absent(self, tmp_path: Path):
        # arrange — releasing a never-quarantined account is not an error
        store = make_store(tmp_path)
        store.upsert(make_account("work"))

        # act / assert
        store.clear_quarantined(AccountName("work"))
        store.clear_quarantined(AccountName("ghost"))
        assert store.quarantined() == []

    def test_remove_drops_the_accounts_quarantine_entry(self, tmp_path: Path):
        # arrange — removing the lineage removes its tombstone too
        store = make_store(tmp_path)
        store.upsert(make_account("work"))
        store.set_quarantined(_quarantine_entry("work"))

        # act
        store.remove(AccountName("work"))

        # assert
        assert store.quarantined() == []


class TestQuarantinedEntryValidation:
    """Malformed quarantine entries fail loudly — same drift rule as records."""

    @staticmethod
    def assert_message(store_root: Path, entries: object, expected: str) -> None:
        # arrange
        write_registry(
            store_root,
            {
                "schemaVersion": 1,
                "order": [],
                "active": None,
                "accounts": {},
                "quarantined": entries,
            },
        )
        store = FileAccountStore(store_root=store_root)

        # act / assert
        with pytest.raises(ValueError) as raised:
            store.quarantined()
        assert str(raised.value) == expected

    def test_entry_not_an_object(self, tmp_path: Path):
        self.assert_message(
            tmp_path / "store",
            ["work"],
            "registry quarantined entry 'work' must be a JSON object",
        )

    def test_entry_missing_a_field(self, tmp_path: Path):
        self.assert_message(
            tmp_path / "store",
            [{"name": "work", "reason": "r", "at": "t"}],
            "registry quarantined entry 'work' is missing fields ['refresh_token_fingerprint']",
        )

    def test_entry_with_an_unknown_field(self, tmp_path: Path):
        self.assert_message(
            tmp_path / "store",
            [
                {
                    "name": "work",
                    "reason": "r",
                    "at": "t",
                    "refresh_token_fingerprint": None,
                    "surprise": 1,
                }
            ],
            "registry quarantined entry 'work' has unknown fields ['surprise']",
        )

    def test_entry_field_of_the_wrong_type(self, tmp_path: Path):
        self.assert_message(
            tmp_path / "store",
            [{"name": "work", "reason": 3, "at": "t", "refresh_token_fingerprint": None}],
            "registry quarantined entry 'work': reason must be a str, got 3",
        )

    def test_entry_missing_the_name_field_falls_back_to_the_raw_item(self, tmp_path: Path):
        # arrange — with no 'name' to label it, the whole entry is quoted
        self.assert_message(
            tmp_path / "store",
            [{"reason": "r", "at": "t", "refresh_token_fingerprint": None}],
            "registry quarantined entry {'reason': 'r', 'at': 't', "
            "'refresh_token_fingerprint': None} is missing fields ['name']",
        )

    def test_fingerprint_of_the_wrong_type(self, tmp_path: Path):
        self.assert_message(
            tmp_path / "store",
            [{"name": "work", "reason": "r", "at": "t", "refresh_token_fingerprint": 3}],
            "registry quarantined entry 'work': refresh_token_fingerprint "
            "must be a str or null, got 3",
        )
