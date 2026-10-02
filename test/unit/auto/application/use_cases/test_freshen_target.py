"""FreshenTarget: parked-credential liveness check before the engine activates it."""

from support.controllable_clock import ControllableClock
from support.fake_credential_store import FakeCredentialStore
from support.fake_token_refresher import FakeTokenRefresher

from claude_acc_manager.auto.application.use_cases.freshen_target import FreshenTarget
from claude_acc_manager.usage.application.ports import (
    AnthropicApiError,
    HttpTransportError,
    RefreshedTokens,
)
from claude_acc_manager.usage.domain.oauth_credential import StoredOAuthCredential

NOW_S = 1_700_000_000.0
NOW_MS = NOW_S * 1000.0


def _credential(*, expires_at_ms: float | None, refresh_token: str | None = "rt-1"):
    return StoredOAuthCredential(
        access_token="at-old", refresh_token=refresh_token, expires_at_ms=expires_at_ms
    )


def _fresh(expires_at_ms: float | None = NOW_MS + 3_600_000.0):
    return _credential(expires_at_ms=expires_at_ms)


class TestFreshenTarget:
    def test_unexpired_credential_is_ok_without_a_refresh(self):
        # Arrange
        credentials = FakeCredentialStore(credentials={"work": _fresh()})
        refresher = FakeTokenRefresher(refreshed=RefreshedTokens("at-new", "rt-new", 3600.0))
        freshen = FreshenTarget(refresher, credentials, ControllableClock(NOW_S))

        # Act
        outcome = freshen.execute("work")

        # Assert
        assert outcome == "ok"
        assert refresher.requests == []
        assert credentials.rotations == []

    def test_missing_credential_is_transient(self):
        # Arrange
        credentials = FakeCredentialStore()
        refresher = FakeTokenRefresher(refreshed=RefreshedTokens("at-new", "rt-new", 3600.0))
        freshen = FreshenTarget(refresher, credentials, ControllableClock(NOW_S))

        # Act / Assert
        assert freshen.execute("work") == "transient"
        assert refresher.requests == []

    def test_missing_expiry_is_ok_without_a_refresh(self):
        # Arrange — schema drift, not staleness (oauth_credential.token_expired)
        credentials = FakeCredentialStore(credentials={"work": _fresh(None)})
        refresher = FakeTokenRefresher(refreshed=RefreshedTokens("at-new", "rt-new", 3600.0))
        freshen = FreshenTarget(refresher, credentials, ControllableClock(NOW_S))

        # Act / Assert
        assert freshen.execute("work") == "ok"
        assert refresher.requests == []

    def test_expired_credential_refreshes_and_persists_rotation(self):
        # Arrange
        credentials = FakeCredentialStore(
            credentials={"work": _credential(expires_at_ms=NOW_MS - 1.0)}
        )
        refresher = FakeTokenRefresher(refreshed=RefreshedTokens("at-new", "rt-new", 3600.0))
        freshen = FreshenTarget(refresher, credentials, ControllableClock(NOW_S))

        # Act
        outcome = freshen.execute("work")

        # Assert
        assert outcome == "ok"
        assert refresher.requests == ["rt-1"]
        assert credentials.rotations == [("work", "at-new", "rt-new", NOW_MS + 3_600_000.0)]

    def test_within_skew_window_counts_as_expired(self):
        # Arrange — 4 minutes out, inside the 5-minute refresh buffer
        credentials = FakeCredentialStore(
            credentials={"work": _credential(expires_at_ms=NOW_MS + 240_000.0)}
        )
        refresher = FakeTokenRefresher(refreshed=RefreshedTokens("at-new", None, 3600.0))
        freshen = FreshenTarget(refresher, credentials, ControllableClock(NOW_S))

        # Act / Assert — refresh_token=None keeps the parked one
        assert freshen.execute("work") == "ok"
        assert credentials.rotations == [("work", "at-new", "rt-1", NOW_MS + 3_600_000.0)]

    def test_expired_without_refresh_token_is_dead(self):
        # Arrange
        credentials = FakeCredentialStore(
            credentials={"work": _credential(expires_at_ms=NOW_MS - 1.0, refresh_token=None)}
        )
        refresher = FakeTokenRefresher(refreshed=RefreshedTokens("at-new", "rt-new", 3600.0))
        freshen = FreshenTarget(refresher, credentials, ControllableClock(NOW_S))

        # Act / Assert
        assert freshen.execute("work") == "dead"
        assert refresher.requests == []

    def test_invalid_grant_is_dead(self):
        # Arrange
        credentials = FakeCredentialStore(
            credentials={"work": _credential(expires_at_ms=NOW_MS - 1.0)}
        )
        refresher = FakeTokenRefresher(
            error=AnthropicApiError(status=400, error_code="invalid_grant")
        )
        freshen = FreshenTarget(refresher, credentials, ControllableClock(NOW_S))

        # Act / Assert
        assert freshen.execute("work") == "dead"
        assert credentials.rotations == []

    def test_other_api_error_is_transient(self):
        # Arrange
        credentials = FakeCredentialStore(
            credentials={"work": _credential(expires_at_ms=NOW_MS - 1.0)}
        )
        refresher = FakeTokenRefresher(
            error=AnthropicApiError(status=500, error_code="server_error")
        )
        freshen = FreshenTarget(refresher, credentials, ControllableClock(NOW_S))

        # Act / Assert
        assert freshen.execute("work") == "transient"
        assert credentials.rotations == []

    def test_transport_error_is_transient(self):
        # Arrange
        credentials = FakeCredentialStore(
            credentials={"work": _credential(expires_at_ms=NOW_MS - 1.0)}
        )
        refresher = FakeTokenRefresher(error=HttpTransportError("connection refused"))
        freshen = FreshenTarget(refresher, credentials, ControllableClock(NOW_S))

        # Act / Assert
        assert freshen.execute("work") == "transient"
        assert credentials.rotations == []
