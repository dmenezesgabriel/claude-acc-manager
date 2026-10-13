"""``FileAccountStore`` — the CRUD surface and the active pointer.

The adapter is real, rooted at a tmp dir; mutations are asserted by reading
the registry document back off disk.
"""

import threading
from pathlib import Path

import pytest
from support.file_store_rigs import make_account, make_store, registry_doc, write_registry

from claude_acc_manager.accounts.application.ports import AccountStorePort
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.accounts.infrastructure.file_account_store import (
    FileAccountStore,
)


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
        # arrange — org fields optional on a fresh login
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
