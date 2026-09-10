"""Contract tests for the shared InMemoryAccountStore fake.

The fake stands in for FileAccountStore in every use-case test, so its
contract-critical edges are pinned here — a drift bug in the fake would
otherwise weaken every test that depends on it (which is how the first M3
attempt shipped a hollow "clears active pointer" assertion).
"""

from pathlib import Path

import pytest
from support.in_memory_account_store import InMemoryAccountStore

from claude_acc_manager.accounts.domain.entities import Account
from claude_acc_manager.accounts.domain.value_objects import AccountName


def _account(name: str = "work", *, enabled: bool = True) -> Account:
    return Account(
        name=AccountName(name),
        email=f"{name}@example.com",
        account_uuid=f"acc-{name}",
        organization_uuid=None,
        organization_name=None,
        added_at="2026-09-10T12:00:00Z",
        enabled=enabled,
    )


class TestInMemoryAccountStoreContract:
    """The fake matches FileAccountStore's observable guarantees."""

    def test_upsert_appends_new_and_replaces_existing_without_reordering(self):
        # arrange
        store = InMemoryAccountStore(Path("/s"))
        store.upsert(_account("work"))
        store.upsert(_account("personal"))

        # act
        store.upsert(_account("work", enabled=False))

        # assert
        assert [a.name.value for a in store.list_accounts()] == ["work", "personal"]
        assert store.get(AccountName("work")).enabled is False

    def test_remove_unknown_raises_key_error(self):
        # arrange
        store = InMemoryAccountStore(Path("/s"))

        # act / assert
        with pytest.raises(KeyError):
            store.remove(AccountName("ghost"))

    def test_remove_clears_an_active_pointer_aimed_at_it(self):
        # arrange
        store = InMemoryAccountStore(Path("/s"))
        store.upsert(_account("work"))
        store.set_active(AccountName("work"))

        # act
        store.remove(AccountName("work"))

        # assert
        assert store.active() is None

    def test_remove_keeps_an_active_pointer_aimed_elsewhere(self):
        # arrange
        store = InMemoryAccountStore(Path("/s"))
        store.upsert(_account("work"))
        store.upsert(_account("personal"))
        store.set_active(AccountName("personal"))

        # act
        store.remove(AccountName("work"))

        # assert
        assert store.active() == _account("personal")

    def test_set_enabled_unknown_raises_key_error(self):
        # arrange
        store = InMemoryAccountStore(Path("/s"))

        # act / assert
        with pytest.raises(KeyError):
            store.set_enabled(AccountName("ghost"), enabled=False)

    def test_active_returns_none_for_a_dangling_pointer(self):
        # arrange
        store = InMemoryAccountStore(Path("/s"))
        store.set_active(AccountName("work"))  # never upserted

        # act / assert
        assert store.active() is None

    def test_account_dir_is_under_the_store_root(self):
        # arrange
        store = InMemoryAccountStore(Path("/s"))

        # act / assert
        assert store.account_dir(AccountName("work")) == Path("/s/accounts/work")
