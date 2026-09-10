"""Unit tests for accounts.domain.entities — Account."""

import dataclasses
from pathlib import Path

import pytest

from claude_acc_manager.accounts.domain.entities import Account
from claude_acc_manager.accounts.domain.value_objects import AccountName


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


class TestAccountConstruction:
    """The entity captures the oauthAccount identity captured at add time."""

    def test_fields_round_trip(self):
        # arrange
        # act
        account = make_account()

        # assert
        assert account.name == AccountName("work")
        assert account.email == "user@example.com"
        assert account.account_uuid == "acc-uuid-1"
        assert account.organization_uuid == "org-uuid-1"
        assert account.organization_name == "ExampleOrg"
        assert account.added_at == "2026-09-10T12:00:00Z"

    def test_enabled_defaults_to_true(self):
        # arrange
        # act
        account = make_account()

        # assert
        assert account.enabled is True

    def test_organization_fields_are_optional(self):
        # arrange — fresh-login credentials carry no org sibling (M0 probe)
        # act
        account = make_account(organization_uuid=None, organization_name=None)

        # assert
        assert account.organization_uuid is None
        assert account.organization_name is None


class TestAccountValueSemantics:
    """Two accounts are equal when every field matches; the entity is
    immutable and hashable."""

    def test_equal_when_all_fields_match(self):
        # arrange / act / assert
        assert make_account() == make_account()
        assert len({make_account(), make_account()}) == 1

    def test_not_equal_when_a_field_differs(self):
        # arrange / act / assert
        assert make_account() != make_account(email="other@example.com")
        assert make_account() != make_account(enabled=False)

    def test_name_distinguishes_accounts_with_same_identity(self):
        # arrange — the name is the registry key, identity fields are metadata
        # act / assert
        assert make_account(name="work") != make_account(name="personal")

    def test_fields_are_frozen(self):
        # arrange
        account = make_account()

        # act / assert
        with pytest.raises(dataclasses.FrozenInstanceError):
            account.email = "mutated@example.com"  # type: ignore[misc]


class TestAccountWithoutPathKnowledge:
    """The entity holds no filesystem paths: the store owns the layout
    (accounts/<name>/ is derived from the registry key)."""

    def test_no_path_attributes_on_the_entity(self):
        # arrange
        account = make_account()

        # act / assert — dataclass fields only, none is a path
        assert not any(isinstance(v, Path) for v in account.__dict__.values())
