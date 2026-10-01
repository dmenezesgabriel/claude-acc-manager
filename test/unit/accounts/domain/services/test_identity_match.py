"""Unit tests for accounts.domain.services.identity_match."""

from claude_acc_manager.accounts.domain.entities import Account
from claude_acc_manager.accounts.domain.services.identity_match import match_account_by_uuid
from claude_acc_manager.accounts.domain.value_objects import AccountName


def _account(name: str, account_uuid: str) -> Account:
    return Account(
        name=AccountName(name),
        email=f"{name}@example.com",
        account_uuid=account_uuid,
        organization_uuid=None,
        organization_name=None,
        added_at="2026-09-10T12:00:00Z",
    )


class TestMatchAccountByUuid:
    def test_names_the_account_owning_the_uuid(self):
        accounts = [_account("a", "uuid-a"), _account("b", "uuid-b")]
        assert match_account_by_uuid(accounts, "uuid-b") == "b"

    def test_an_unknown_uuid_matches_nothing(self):
        accounts = [_account("a", "uuid-a")]
        assert match_account_by_uuid(accounts, "uuid-elsewhere") is None

    def test_an_empty_registry_matches_nothing(self):
        assert match_account_by_uuid([], "uuid-a") is None

    def test_the_first_registry_entry_wins_a_shared_uuid(self):
        # two records claiming one uuid is corruption, not a supported shape —
        # pin the deterministic pick so callers never see a random one
        accounts = [_account("a", "uuid-x"), _account("b", "uuid-x")]
        assert match_account_by_uuid(accounts, "uuid-x") == "a"
