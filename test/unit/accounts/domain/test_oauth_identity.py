"""Unit tests for accounts.domain.oauth_identity."""

import pytest

from claude_acc_manager.accounts.domain.oauth_identity import (
    OAuthIdentity,
    oauth_identity_from_config,
)


def _config(**oauth_account: object) -> dict[str, object]:
    """A ~/.claude.json-shaped config carrying *oauth_account* under its key."""
    return {"numStartups": 3, "oauthAccount": dict(oauth_account)}


class TestOAuthIdentityFromConfigHappyPath:
    """A full oauthAccount block parses into a typed identity."""

    def test_all_fields_present(self):
        # arrange
        config = _config(
            emailAddress="user@example.com",
            accountUuid="acc-123",
            organizationUuid="org-456",
            organizationName="Test Org",
        )

        # act
        identity = oauth_identity_from_config(config)

        # assert
        assert identity == OAuthIdentity(
            email="user@example.com",
            account_uuid="acc-123",
            organization_uuid="org-456",
            organization_name="Test Org",
        )

    def test_optional_org_fields_absent_become_none(self):
        # arrange — a fresh login carries no org sibling (M0 probe 2026-09-10)
        config = _config(emailAddress="user@example.com", accountUuid="acc-123")

        # act
        identity = oauth_identity_from_config(config)

        # assert
        assert identity is not None
        assert identity.organization_uuid is None
        assert identity.organization_name is None

    def test_optional_org_fields_wrong_type_become_none(self):
        # arrange
        config = _config(
            emailAddress="user@example.com",
            accountUuid="acc-123",
            organizationUuid=42,
            organizationName=["nope"],
        )

        # act
        identity = oauth_identity_from_config(config)

        # assert
        assert identity is not None
        assert identity.organization_uuid is None
        assert identity.organization_name is None


class TestOAuthIdentityFromConfigNoLogin:
    """No oauthAccount key means no account is logged in — not an error."""

    def test_missing_key_returns_none(self):
        # arrange / act / assert
        assert oauth_identity_from_config({"numStartups": 3}) is None

    def test_null_value_returns_none(self):
        # arrange / act / assert
        assert oauth_identity_from_config({"oauthAccount": None}) is None


class TestOAuthIdentityFromConfigRejects:
    """A present-but-broken oauthAccount surfaces as ValueError naming the
    offending value and the expected shape (CLAUDE.md exception rule)."""

    def test_oauth_account_not_an_object(self):
        # arrange / act
        with pytest.raises(ValueError) as raised:
            oauth_identity_from_config({"oauthAccount": "user@example.com"})

        # assert
        assert str(raised.value) == ("oauthAccount is 'user@example.com', expected a JSON object")

    def test_email_missing(self):
        # arrange / act
        with pytest.raises(ValueError) as raised:
            oauth_identity_from_config(_config(accountUuid="acc-123"))

        # assert
        assert str(raised.value) == (
            "oauthAccount.emailAddress is None, expected a non-empty string"
        )

    def test_email_empty(self):
        # arrange / act
        with pytest.raises(ValueError) as raised:
            oauth_identity_from_config(_config(emailAddress="", accountUuid="acc-123"))

        # assert
        assert str(raised.value) == ("oauthAccount.emailAddress is '', expected a non-empty string")

    def test_email_not_a_string(self):
        # arrange / act
        with pytest.raises(ValueError) as raised:
            oauth_identity_from_config(_config(emailAddress=123, accountUuid="acc-123"))

        # assert
        assert str(raised.value) == (
            "oauthAccount.emailAddress is 123, expected a non-empty string"
        )

    def test_account_uuid_missing(self):
        # arrange / act
        with pytest.raises(ValueError) as raised:
            oauth_identity_from_config(_config(emailAddress="user@example.com"))

        # assert
        assert str(raised.value) == (
            "oauthAccount.accountUuid is None, expected a non-empty string"
        )

    def test_account_uuid_empty(self):
        # arrange / act
        with pytest.raises(ValueError) as raised:
            oauth_identity_from_config(_config(emailAddress="user@example.com", accountUuid=""))

        # assert
        assert str(raised.value) == ("oauthAccount.accountUuid is '', expected a non-empty string")


class TestOAuthIdentityValueSemantics:
    """The identity is an immutable, hashable value object."""

    def test_equal_when_all_fields_match(self):
        # arrange
        one = OAuthIdentity("e", "a", None, None)
        same = OAuthIdentity("e", "a", None, None)

        # act / assert
        assert one == same
        assert len({one, same}) == 1

    def test_frozen(self):
        # arrange
        identity = OAuthIdentity("e", "a", None, None)

        # act / assert
        with pytest.raises(AttributeError):
            identity.email = "other"  # type: ignore[misc]
