"""Unit tests for accounts.infrastructure.file_account_store and the
AccountStorePort it implements."""

import json
import threading
from pathlib import Path

import pytest

from claude_acc_manager.accounts.application.ports import AccountStorePort
from claude_acc_manager.accounts.domain.entities import Account, QuarantineEntry
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.accounts.infrastructure.file_account_store import (
    FileAccountStore,
)


def make_account(name: str = "work", **overrides: object) -> Account:
    fields: dict[str, object] = {
        "email": "user@example.com",
        "account_uuid": "acc-uuid-1",
        "organization_uuid": "org-uuid-1",
        "organization_name": "ExampleOrg",
        "added_at": "2026-09-10T12:00:00Z",
    }
    fields.update(overrides)
    return Account(AccountName(name), **fields)  # type: ignore[arg-type]


def make_store(tmp_path: Path) -> FileAccountStore:
    return FileAccountStore(store_root=tmp_path / "store")


def registry_doc(store_root: Path) -> dict[str, object]:
    text = (store_root / "registry.json").read_text(encoding="utf-8")
    return json.loads(text)  # type: ignore[no-any-return]


def write_registry(store_root: Path, document: dict[str, object]) -> None:
    store_root.mkdir(parents=True, exist_ok=True)
    (store_root / "registry.json").write_text(json.dumps(document), encoding="utf-8")


class TestStoreAdaptsThePort:
    """FileAccountStore explicitly subclasses the port (greppable map)."""

    def test_store_is_an_account_store_port(self, tmp_path: Path):
        # arrange
        # act
        store = make_store(tmp_path)

        # assert
        assert isinstance(store, AccountStorePort)


class TestAccountDir:
    """account_dir derives each account's CLAUDE_CONFIG_DIR under the store."""

    def test_derives_account_dir_under_accounts_tree(self, tmp_path: Path):
        # arrange
        store = make_store(tmp_path)

        # act
        directory = store.account_dir(AccountName("work"))

        # assert
        assert directory == tmp_path / "store" / "accounts" / "work"

    def test_dir_is_relative_to_store_root(self, tmp_path: Path):
        # arrange
        store = make_store(tmp_path)

        # act / assert
        assert str(store.account_dir(AccountName("work"))).startswith(str(tmp_path / "store"))


class TestUpsert:
    """Adds append to the registry order; updates keep their position."""

    def test_new_account_is_appended_to_order(self, tmp_path: Path):
        # arrange
        store = make_store(tmp_path)

        # act
        store.upsert(make_account("work"))
        store.upsert(make_account("personal"))

        # assert
        assert [a.name.value for a in store.list_accounts()] == [
            "work",
            "personal",
        ]

    def test_update_keeps_registry_position(self, tmp_path: Path):
        # arrange
        store = make_store(tmp_path)
        store.upsert(make_account("work"))
        store.upsert(make_account("personal"))

        # act
        store.upsert(make_account("work", email="moved@example.com"))

        # assert
        assert [a.name.value for a in store.list_accounts()] == [
            "work",
            "personal",
        ]
        assert store.get(AccountName("work")).email == "moved@example.com"  # type: ignore[union-attr]

    def test_all_fields_round_trip(self, tmp_path: Path):
        # arrange — org fields optional per the M0 probe (fresh login)
        store = make_store(tmp_path)
        account = make_account("work", organization_uuid=None, organization_name=None)

        # act
        store.upsert(account)
        loaded = store.get(AccountName("work"))

        # assert
        assert loaded == account

    def test_persists_across_instances(self, tmp_path: Path):
        # arrange
        store = make_store(tmp_path)

        # act
        store.upsert(make_account("work"))

        # assert
        assert make_store(tmp_path).get(AccountName("work")) is not None

    def test_store_root_is_private(self, tmp_path: Path):
        # arrange
        store = make_store(tmp_path)

        # act
        store.upsert(make_account("work"))

        # assert
        assert (tmp_path / "store").stat().st_mode & 0o777 == 0o700
        assert (tmp_path / "store" / "registry.json").stat().st_mode & 0o777 == 0o600


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


class TestGet:
    """Unknown names return None; known names return the account."""

    def test_unknown_name_returns_none(self, tmp_path: Path):
        # arrange
        store = make_store(tmp_path)

        # act / assert
        assert store.get(AccountName("ghost")) is None

    def test_known_name_returns_account(self, tmp_path: Path):
        # arrange
        store = make_store(tmp_path)
        account = make_account("work")

        # act
        store.upsert(account)

        # assert
        assert store.get(AccountName("work")) == account


class TestRemove:
    """Removal drops the record, its order entry, and an active pointer."""

    def test_removed_account_disappears(self, tmp_path: Path):
        # arrange
        store = make_store(tmp_path)
        store.upsert(make_account("work"))

        # act
        store.remove(AccountName("work"))

        # assert
        assert store.get(AccountName("work")) is None
        assert store.list_accounts() == []

    def test_removing_the_active_account_clears_active(self, tmp_path: Path):
        # arrange
        store = make_store(tmp_path)
        store.upsert(make_account("work"))
        store.set_active(AccountName("work"))

        # act
        store.remove(AccountName("work"))

        # assert — the persisted pointer itself becomes null (a dangling
        # pointer would be masked by active() tolerating unknown names)
        assert store.active() is None
        assert registry_doc(tmp_path / "store")["active"] is None

    def test_removing_a_non_active_account_keeps_active(self, tmp_path: Path):
        # arrange
        store = make_store(tmp_path)
        store.upsert(make_account("work"))
        store.upsert(make_account("personal"))
        store.set_active(AccountName("work"))

        # act
        store.remove(AccountName("personal"))

        # assert
        assert store.active() == make_account("work")

    def test_unknown_name_raises_key_error(self, tmp_path: Path):
        # arrange
        store = make_store(tmp_path)

        # act / assert
        with pytest.raises(KeyError, match="ghost"):
            store.remove(AccountName("ghost"))


class TestSetEnabled:
    """Enabled is a persisted flag on the record."""

    def test_persists_disabled_state(self, tmp_path: Path):
        # arrange
        store = make_store(tmp_path)
        store.upsert(make_account("work"))

        # act
        store.set_enabled(AccountName("work"), False)

        # assert
        assert store.get(AccountName("work")).enabled is False  # type: ignore[union-attr]

    def test_unknown_name_raises_key_error(self, tmp_path: Path):
        # arrange
        store = make_store(tmp_path)

        # act / assert
        with pytest.raises(KeyError, match="ghost"):
            store.set_enabled(AccountName("ghost"), False)


class TestActivePointer:
    """The active account is stored in the registry (docs/architecture.md §3)."""

    def test_active_defaults_to_none(self, tmp_path: Path):
        # arrange
        store = make_store(tmp_path)

        # act / assert
        assert store.active() is None

    def test_set_active_persists(self, tmp_path: Path):
        # arrange
        store = make_store(tmp_path)
        store.upsert(make_account("work"))

        # act
        store.set_active(AccountName("work"))

        # assert
        assert store.active() == make_account("work")

    def test_set_active_to_none(self, tmp_path: Path):
        # arrange
        store = make_store(tmp_path)
        store.upsert(make_account("work"))
        store.set_active(AccountName("work"))

        # act
        store.set_active(None)

        # assert
        assert store.active() is None

    def test_dangling_active_pointer_returns_none(self, tmp_path: Path):
        # arrange — a hand-edited registry pointing at a removed account must
        # not surface a fake account
        store = make_store(tmp_path)
        document = {
            "schemaVersion": 1,
            "order": [],
            "active": "ghost",
            "accounts": {},
            "quarantined": [],
        }
        write_registry(tmp_path / "store", document)

        # act / assert
        assert store.active() is None


class TestLockedMutations:
    """Registry read-modify-write happens under the store's flock."""

    def test_concurrent_upserts_do_not_lose_writes(self, tmp_path: Path):
        # arrange — two independent store instances (two "processes")
        store_root = tmp_path / "store"
        threads: list[threading.Thread] = []
        names = [f"account-{i}" for i in range(8)]
        lock_acquired = threading.Barrier(len(names))

        def upsert_from_thread(name: str) -> None:
            store = FileAccountStore(store_root=store_root)
            lock_acquired.wait(timeout=5)
            store.upsert(make_account(name))

        for name in names:
            threads.append(threading.Thread(target=upsert_from_thread, args=(name,)))

        # act
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # assert — every write landed (a lock-less read-modify-write would
        # lose entries under this concurrency)
        reloaded = FileAccountStore(store_root=store_root)
        assert len(reloaded.list_accounts()) == len(names)

    def test_lock_is_taken_on_the_expected_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # arrange — the lock path is store_root/.lock (docs/architecture.md §3); patch the
        # name where the store module bound it at import time
        captured: list[Path] = []
        from claude_acc_manager.accounts.infrastructure import file_account_store

        original = file_account_store.exclusive_file_lock

        def capture(path: Path, timeout_s: float = 10.0):
            captured.append(path)
            return original(path, timeout_s)

        monkeypatch.setattr(file_account_store, "exclusive_file_lock", capture)
        store = make_store(tmp_path)

        # act
        store.upsert(make_account("work"))

        # assert
        assert captured == [tmp_path / "store" / ".lock"]


def _quarantine_entry(name: str = "work", **overrides: object) -> QuarantineEntry:
    fields: dict[str, object] = {
        "name": name,
        "reason": "permanent_auth_error",
        "at": "2026-09-10T12:00:00Z",
        "refresh_token_fingerprint": "sha256:dead",
    }
    fields.update(overrides)
    return QuarantineEntry(**fields)  # type: ignore[arg-type]


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
