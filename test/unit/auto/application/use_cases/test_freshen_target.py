"""FreshenTarget: parked-credential liveness check before the engine activates it."""

import pytest
from support.controllable_clock import ControllableClock
from support.fake_claude_contract import FakeClaudeContractProbe
from support.fake_credential_store import FakeCredentialStore
from support.fake_token_refresher import FakeTokenRefresher

from claude_acc_manager.auto.application.use_cases.freshen_target import FreshenTarget
from claude_acc_manager.shared.claude_contract import (
    ClaudeContract,
    UnsupportedClaudeVersionError,
    contract_for_version,
)
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


def _probe(contract: ClaudeContract | None = None) -> FakeClaudeContractProbe:
    """A contract probe pinned to *contract* (a verified 2.1.x by default)."""
    return FakeClaudeContractProbe(contract or contract_for_version((2, 1, 288)))


class TestFreshenTarget:
    def test_unexpired_credential_is_ok_without_a_refresh(self):
        # Arrange
        credentials = FakeCredentialStore(credentials={"work": _fresh()})
        refresher = FakeTokenRefresher(refreshed=RefreshedTokens("at-new", "rt-new", 3600.0))
        freshen = FreshenTarget(refresher, credentials, ControllableClock(NOW_S), _probe())

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
        freshen = FreshenTarget(refresher, credentials, ControllableClock(NOW_S), _probe())

        # Act / Assert
        assert freshen.execute("work") == "transient"
        assert refresher.requests == []

    def test_missing_expiry_is_ok_without_a_refresh(self):
        # Arrange — schema drift, not staleness (oauth_credential.token_expired)
        credentials = FakeCredentialStore(credentials={"work": _fresh(None)})
        refresher = FakeTokenRefresher(refreshed=RefreshedTokens("at-new", "rt-new", 3600.0))
        freshen = FreshenTarget(refresher, credentials, ControllableClock(NOW_S), _probe())

        # Act / Assert
        assert freshen.execute("work") == "ok"
        assert refresher.requests == []

    def test_expired_credential_refreshes_and_persists_rotation(self):
        # Arrange
        credentials = FakeCredentialStore(
            credentials={"work": _credential(expires_at_ms=NOW_MS - 1.0)}
        )
        refresher = FakeTokenRefresher(refreshed=RefreshedTokens("at-new", "rt-new", 3600.0))
        freshen = FreshenTarget(refresher, credentials, ControllableClock(NOW_S), _probe())

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
        freshen = FreshenTarget(refresher, credentials, ControllableClock(NOW_S), _probe())

        # Act / Assert — refresh_token=None keeps the parked one
        assert freshen.execute("work") == "ok"
        assert credentials.rotations == [("work", "at-new", "rt-1", NOW_MS + 3_600_000.0)]

    def test_expired_without_refresh_token_is_dead(self):
        # Arrange
        credentials = FakeCredentialStore(
            credentials={"work": _credential(expires_at_ms=NOW_MS - 1.0, refresh_token=None)}
        )
        refresher = FakeTokenRefresher(refreshed=RefreshedTokens("at-new", "rt-new", 3600.0))
        freshen = FreshenTarget(refresher, credentials, ControllableClock(NOW_S), _probe())

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
        freshen = FreshenTarget(refresher, credentials, ControllableClock(NOW_S), _probe())

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
        freshen = FreshenTarget(refresher, credentials, ControllableClock(NOW_S), _probe())

        # Act / Assert
        assert freshen.execute("work") == "transient"
        assert credentials.rotations == []

    def test_transport_error_is_transient(self):
        # Arrange
        credentials = FakeCredentialStore(
            credentials={"work": _credential(expires_at_ms=NOW_MS - 1.0)}
        )
        refresher = FakeTokenRefresher(error=HttpTransportError("connection refused"))
        freshen = FreshenTarget(refresher, credentials, ControllableClock(NOW_S), _probe())

        # Act / Assert
        assert freshen.execute("work") == "transient"
        assert credentials.rotations == []


class TestContractGate:
    """The grant is the one-time-use act: the contract holds before it runs.

    A refused contract propagates — the engine's tick surfaces it as an
    ERROR, never as a retryable "transient" freshen. Every path that never
    refreshes never probes.
    """

    def test_refused_contract_blocks_the_grant_and_the_persist(self):
        # Arrange — expired parked credential + an out-of-band claude
        credentials = FakeCredentialStore(
            credentials={"work": _credential(expires_at_ms=NOW_MS - 1.0)}
        )
        refresher = FakeTokenRefresher(refreshed=RefreshedTokens("at-new", "rt-new", 3600.0))
        probe = _probe(contract_for_version((0, 2, 126)))
        freshen = FreshenTarget(refresher, credentials, ControllableClock(NOW_S), probe)

        # Act / Assert
        with pytest.raises(UnsupportedClaudeVersionError, match="0.2.126"):
            freshen.execute("work")
        assert refresher.requests == []
        assert credentials.rotations == []
        assert probe.probes == 1

    def test_undetermined_version_refuses(self):
        # Arrange
        credentials = FakeCredentialStore(
            credentials={"work": _credential(expires_at_ms=NOW_MS - 1.0)}
        )
        refresher = FakeTokenRefresher()
        freshen = FreshenTarget(
            refresher,
            credentials,
            ControllableClock(NOW_S),
            _probe(contract_for_version(None)),
        )

        # Act / Assert
        with pytest.raises(UnsupportedClaudeVersionError, match="could not determine"):
            freshen.execute("work")
        assert refresher.requests == []

    def test_an_assumed_contract_refreshes(self):
        # Arrange — the override-bypassed contract lets the grant run
        assumed = ClaudeContract(version=(2, 2, 0), supported=True, assumed=True, reason=None)
        credentials = FakeCredentialStore(
            credentials={"work": _credential(expires_at_ms=NOW_MS - 1.0)}
        )
        refresher = FakeTokenRefresher(refreshed=RefreshedTokens("at-new", "rt-new", 3600.0))
        freshen = FreshenTarget(refresher, credentials, ControllableClock(NOW_S), _probe(assumed))

        # Act / Assert
        assert freshen.execute("work") == "ok"
        assert refresher.requests == ["rt-1"]

    def test_unexpired_credential_never_probes(self):
        # Arrange — the ok short-circuit is a read; it must not consult claude
        credentials = FakeCredentialStore(credentials={"work": _fresh()})
        refresher = FakeTokenRefresher()
        probe = _probe(contract_for_version(None))
        freshen = FreshenTarget(refresher, credentials, ControllableClock(NOW_S), probe)

        # Act / Assert
        assert freshen.execute("work") == "ok"
        assert probe.probes == 0

    def test_expired_without_refresh_token_never_probes(self):
        # Arrange — the dead verdict needs no grant, so no gate either
        credentials = FakeCredentialStore(
            credentials={"work": _credential(expires_at_ms=NOW_MS - 1.0, refresh_token=None)}
        )
        refresher = FakeTokenRefresher()
        probe = _probe(contract_for_version(None))
        freshen = FreshenTarget(refresher, credentials, ControllableClock(NOW_S), probe)

        # Act / Assert
        assert freshen.execute("work") == "dead"
        assert probe.probes == 0

    def test_missing_credential_never_probes(self):
        # Arrange
        credentials = FakeCredentialStore()
        refresher = FakeTokenRefresher()
        probe = _probe(contract_for_version(None))
        freshen = FreshenTarget(refresher, credentials, ControllableClock(NOW_S), probe)

        # Act / Assert
        assert freshen.execute("work") == "transient"
        assert probe.probes == 0
