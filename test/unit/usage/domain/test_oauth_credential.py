"""Unit tests for usage.domain.oauth_credential.

Ports claude-swap oauth.py's is_oauth_token_expired (5-minute skew, epoch
milliseconds) onto our own token_expired function.
"""

from claude_acc_manager.usage.domain.oauth_credential import DEFAULT_SKEW_MS, token_expired

NOW_MS = 1_000_000_000.0


class TestTokenExpired:
    def test_well_before_the_skew_window_is_not_expired(self):
        assert token_expired(NOW_MS + 600_000.0, NOW_MS) is False

    def test_already_past_is_expired(self):
        assert token_expired(NOW_MS - 1_000.0, NOW_MS) is True

    def test_exactly_at_the_skew_boundary_is_expired(self):
        # claude-swap: now_ms + BUFFER >= expires_at -> inclusive boundary
        assert token_expired(NOW_MS + DEFAULT_SKEW_MS, NOW_MS) is True

    def test_just_outside_the_skew_boundary_is_not_expired(self):
        assert token_expired(NOW_MS + DEFAULT_SKEW_MS + 1.0, NOW_MS) is False

    def test_missing_expiry_is_never_expired(self):
        # a credential with no expiresAt is schema drift, not evidence of
        # staleness (claude-swap: non-numeric expires_at -> not expired)
        assert token_expired(None, NOW_MS) is False

    def test_custom_skew_is_honored(self):
        assert token_expired(NOW_MS + 10_000.0, NOW_MS, skew_ms=20_000.0) is True
        assert token_expired(NOW_MS + 30_000.0, NOW_MS, skew_ms=20_000.0) is False
