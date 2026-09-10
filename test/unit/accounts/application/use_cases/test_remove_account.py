"""Unit tests for accounts.application.use_cases.remove_account."""

from pathlib import Path

import pytest
from support.in_memory_account_store import InMemoryAccountStore

from claude_acc_manager.accounts.application.use_cases.remove_account import RemoveAccount
from claude_acc_manager.accounts.domain.entities import Account
from claude_acc_manager.accounts.domain.value_objects import AccountName


def _account(name: str) -> Account:
    return Account(
        name=AccountName(name),
        email=f"{name}@example.com",
        account_uuid=f"acc-{name}",
        organization_uuid=None,
        organization_name=None,
        added_at="2026-09-10T12:00:00Z",
        enabled=True,
    )


def _store_with(tmp_path: Path, *names: str) -> InMemoryAccountStore:
    store = InMemoryAccountStore(tmp_path)
    for name in names:
        store.upsert(_account(name))
        store.account_dir(AccountName(name)).mkdir(parents=True)
    return store


class TestRemoveAccount:
    """RemoveAccount drops the registry entry and the captured login dir."""

    def test_removes_the_record_and_deletes_the_account_dir(self, tmp_path: Path):
        # arrange
        store = _store_with(tmp_path, "work")
        (store.account_dir(AccountName("work")) / ".credentials.json").write_text("{}")

        # act
        RemoveAccount(store).execute(AccountName("work"))

        # assert
        assert store.get(AccountName("work")) is None
        assert not store.account_dir(AccountName("work")).exists()

    def test_unknown_account_raises_key_error_and_touches_nothing(self, tmp_path: Path):
        # arrange
        store = _store_with(tmp_path, "work")

        # act / assert
        with pytest.raises(KeyError):
            RemoveAccount(store).execute(AccountName("personal"))
        assert store.get(AccountName("work")) is not None

    def test_succeeds_when_the_account_dir_was_never_created(self, tmp_path: Path):
        # arrange — account registered but no dir on disk (login dir cleaned out)
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))

        # act
        RemoveAccount(store).execute(AccountName("work"))

        # assert
        assert store.get(AccountName("work")) is None

    def test_leaves_other_accounts_and_their_dirs_intact(self, tmp_path: Path):
        # arrange
        store = _store_with(tmp_path, "work", "personal")

        # act
        RemoveAccount(store).execute(AccountName("work"))

        # assert
        assert store.get(AccountName("personal")) is not None
        assert store.account_dir(AccountName("personal")).exists()
