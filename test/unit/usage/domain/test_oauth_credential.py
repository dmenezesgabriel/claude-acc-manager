"""Unit tests for usage.domain.oauth_credential.

The expiry contract: a 5-minute skew window, epoch milliseconds, and a
missing expiry that is never treated as stale.
"""

from claude_acc_manager.usage.domain.oauth_credential import (
    DEFAULT_SKEW_MS,
    StoredOAuthCredential,
    stored_credential_from_claude_ai_oauth,
    token_expired,
)

NOW_MS = 1_000_000_000.0


class TestTokenExpired:
    def test_well_before_the_skew_window_is_not_expired(self):
        assert token_expired(NOW_MS + 600_000.0, NOW_MS) is False

    def test_already_past_is_expired(self):
        assert token_expired(NOW_MS - 1_000.0, NOW_MS) is True

    def test_exactly_at_the_skew_boundary_is_expired(self):
        # now_ms + skew >= expires_at — the boundary itself counts as expired
        assert token_expired(NOW_MS + DEFAULT_SKEW_MS, NOW_MS) is True

    def test_just_outside_the_skew_boundary_is_not_expired(self):
        assert token_expired(NOW_MS + DEFAULT_SKEW_MS + 1.0, NOW_MS) is False

    def test_missing_expiry_is_never_expired(self):
        # a credential with no expiresAt is schema drift, not evidence of
        # staleness
        assert token_expired(None, NOW_MS) is False

    def test_custom_skew_is_honored(self):
        assert token_expired(NOW_MS + 10_000.0, NOW_MS, skew_ms=20_000.0) is True
        assert token_expired(NOW_MS + 30_000.0, NOW_MS, skew_ms=20_000.0) is False


class TestStoredCredentialFromClaudeAiOauth:
    """Parses the ``claudeAiOauth`` block of a stored .credentials.json file."""

    def test_parses_a_full_block(self):
        credential = stored_credential_from_claude_ai_oauth(
            {"accessToken": "at-1", "refreshToken": "rt-1", "expiresAt": 1_700_000_000_000}
        )
        assert credential == StoredOAuthCredential(
            access_token="at-1", refresh_token="rt-1", expires_at_ms=1_700_000_000_000.0
        )

    def test_missing_access_token_is_no_usable_credential(self):
        assert stored_credential_from_claude_ai_oauth({"refreshToken": "rt-1"}) is None

    def test_blank_access_token_is_no_usable_credential(self):
        assert stored_credential_from_claude_ai_oauth({"accessToken": ""}) is None

    def test_non_string_access_token_is_no_usable_credential(self):
        assert stored_credential_from_claude_ai_oauth({"accessToken": 42}) is None

    def test_missing_refresh_token_is_none(self):
        credential = stored_credential_from_claude_ai_oauth({"accessToken": "at-1"})
        assert credential is not None
        assert credential.refresh_token is None

    def test_blank_refresh_token_is_none(self):
        credential = stored_credential_from_claude_ai_oauth(
            {"accessToken": "at-1", "refreshToken": ""}
        )
        assert credential is not None
        assert credential.refresh_token is None

    def test_missing_expiry_is_none(self):
        credential = stored_credential_from_claude_ai_oauth({"accessToken": "at-1"})
        assert credential is not None
        assert credential.expires_at_ms is None

    def test_non_numeric_expiry_is_none(self):
        credential = stored_credential_from_claude_ai_oauth(
            {"accessToken": "at-1", "expiresAt": "soon"}
        )
        assert credential is not None
        assert credential.expires_at_ms is None

    def test_bool_expiry_is_none(self):
        # bool is an int subclass — must not pass as a numeric timestamp
        credential = stored_credential_from_claude_ai_oauth(
            {"accessToken": "at-1", "expiresAt": True}
        )
        assert credential is not None
        assert credential.expires_at_ms is None
