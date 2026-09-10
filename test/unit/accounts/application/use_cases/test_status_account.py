"""Unit tests for accounts.application.use_cases.status_account."""

from pathlib import Path

import pytest
from support.fake_active_slot import FakeActiveSlot
from support.in_memory_account_store import InMemoryAccountStore

from claude_acc_manager.accounts.application.use_cases.status_account import StatusAccount
from claude_acc_manager.accounts.domain.entities import Account
from claude_acc_manager.accounts.domain.value_objects import AccountName


def _config(account_uuid: str = "acc-123", email: str = "user@example.com") -> dict[str, object]:
    return {
        "oauthAccount": {
            "emailAddress": email,
            "accountUuid": account_uuid,
            "organizationUuid": "org-456",
            "organizationName": "Test Org",
        },
    }


def _account(name: str, account_uuid: str) -> Account:
    return Account(
        name=AccountName(name),
        email=f"{name}@example.com",
        account_uuid=account_uuid,
        organization_uuid="org-456",
        organization_name="Test Org",
        added_at="2026-09-10T12:00:00Z",
        enabled=True,
    )


class TestStatusAccountNoLiveAccount:
    """No config, or a config with no login, means no active account."""

    def test_returns_none_when_no_config_file(self, tmp_path: Path):
        # arrange
        use_case = StatusAccount(FakeActiveSlot(config=None), InMemoryAccountStore(tmp_path))

        # act / assert
        assert use_case.execute() is None

    def test_returns_none_when_config_has_no_oauth_account(self, tmp_path: Path):
        # arrange
        use_case = StatusAccount(
            FakeActiveSlot(config={"numStartups": 3}), InMemoryAccountStore(tmp_path)
        )

        # act / assert
        assert use_case.execute() is None


class TestStatusAccountIdentifiesTheLiveSlot:
    """The live slot's oauthAccount identity is reported and matched against
    the registry by account UUID."""

    def test_reports_the_identity_and_names_the_managed_account(self, tmp_path: Path):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work", account_uuid="acc-123"))
        use_case = StatusAccount(FakeActiveSlot(config=_config(account_uuid="acc-123")), store)

        # act
        status = use_case.execute()

        # assert
        assert status is not None
        assert status.email == "user@example.com"
        assert status.account_uuid == "acc-123"
        assert status.organization_uuid == "org-456"
        assert status.organization_name == "Test Org"
        assert status.managed_as == "work"

    def test_managed_as_is_none_when_the_live_uuid_is_not_in_the_registry(self, tmp_path: Path):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work", account_uuid="acc-OTHER"))
        use_case = StatusAccount(FakeActiveSlot(config=_config(account_uuid="acc-123")), store)

        # act
        status = use_case.execute()

        # assert
        assert status is not None
        assert status.managed_as is None

    def test_matches_by_uuid_not_by_email(self, tmp_path: Path):
        # arrange — same person, different account UUID: not the managed one
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work", account_uuid="acc-OLD"))
        use_case = StatusAccount(
            FakeActiveSlot(config=_config(account_uuid="acc-NEW", email="work@example.com")),
            store,
        )

        # act
        status = use_case.execute()

        # assert
        assert status is not None
        assert status.managed_as is None

    def test_torn_oauth_account_block_propagates_as_value_error(self, tmp_path: Path):
        # arrange
        use_case = StatusAccount(
            FakeActiveSlot(config={"oauthAccount": "not-an-object"}),
            InMemoryAccountStore(tmp_path),
        )

        # act / assert
        with pytest.raises(ValueError, match="expected a JSON object"):
            use_case.execute()
