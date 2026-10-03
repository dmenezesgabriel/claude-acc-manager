"""Unit tests for usage.domain.resolved_identity."""

from claude_acc_manager.usage.domain.resolved_identity import (
    ResolvedIdentity,
    resolved_identity_from_profile_response,
)


class TestResolvesAFullIdentity:
    """A well-formed profile response resolves uuid/email/organization_uuid."""

    def test_parses_account_and_organization(self):
        # arrange
        data = {
            "account": {"uuid": "acc-123", "email": "user@example.com"},
            "organization": {"uuid": "org-456"},
        }

        # act
        identity = resolved_identity_from_profile_response(data)

        # assert
        assert identity == ResolvedIdentity(
            account_uuid="acc-123", email="user@example.com", organization_uuid="org-456"
        )

    def test_email_and_organization_are_optional(self):
        # arrange — a uuid-only response still resolves
        data = {"account": {"uuid": "acc-123"}}

        # act
        identity = resolved_identity_from_profile_response(data)

        # assert
        assert identity == ResolvedIdentity(
            account_uuid="acc-123", email=None, organization_uuid=None
        )


class TestUnresolvableIsNone:
    """Anything short of a usable account.uuid resolves to None, never raises."""

    def test_missing_account_is_none(self):
        assert resolved_identity_from_profile_response({}) is None

    def test_account_not_an_object_is_none(self):
        assert resolved_identity_from_profile_response({"account": "not-an-object"}) is None

    def test_missing_uuid_is_none(self):
        assert resolved_identity_from_profile_response({"account": {"email": "a@b.c"}}) is None

    def test_blank_uuid_is_none(self):
        assert resolved_identity_from_profile_response({"account": {"uuid": "   "}}) is None

    def test_non_string_uuid_is_none(self):
        assert resolved_identity_from_profile_response({"account": {"uuid": 123}}) is None

    def test_organization_not_an_object_is_ignored_not_fatal(self):
        # arrange
        data = {"account": {"uuid": "acc-123"}, "organization": "not-an-object"}

        # act
        identity = resolved_identity_from_profile_response(data)

        # assert
        assert identity == ResolvedIdentity(
            account_uuid="acc-123", email=None, organization_uuid=None
        )
