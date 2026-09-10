"""Unit tests for accounts.application.use_cases.list_accounts."""

from pathlib import Path

from support.in_memory_account_store import InMemoryAccountStore

from claude_acc_manager.accounts.application.use_cases.list_accounts import ListAccounts
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


class TestListAccounts:
    """ListAccounts returns every account in registry order, active marked."""

    def test_empty_store_yields_no_summaries(self, tmp_path: Path):
        # arrange
        store = InMemoryAccountStore(tmp_path)

        # act / assert
        assert ListAccounts(store).execute() == []

    def test_preserves_registry_order(self, tmp_path: Path):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        store.upsert(_account("personal"))

        # act
        result = ListAccounts(store).execute()

        # assert
        assert [summary.account.name.value for summary in result] == ["work", "personal"]

    def test_marks_only_the_active_account(self, tmp_path: Path):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        store.upsert(_account("personal"))
        store.set_active(AccountName("personal"))

        # act
        result = ListAccounts(store).execute()

        # assert
        assert [summary.is_active for summary in result] == [False, True]

    def test_no_account_is_marked_when_none_is_active(self, tmp_path: Path):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))

        # act
        result = ListAccounts(store).execute()

        # assert
        assert result[0].is_active is False
