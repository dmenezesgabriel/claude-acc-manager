"""``AnthropicTokenRefresher`` — the refresh endpoint's wire contract.

Header sets, URL, and timeouts are pinned exactly — this endpoint gets its
own minimal header set, not a uniform one (ADR-0007).
"""

import json
from pathlib import Path

import pytest
from support.fake_http_transport import FakeHttpTransport

from claude_acc_manager.usage.application.ports import (
    AnthropicApiError,
    HttpResponse,
    HttpTransportError,
    TokenRefresherPort,
)
from claude_acc_manager.usage.infrastructure.anthropic_oauth import (
    OAUTH_CLIENT_ID,
    TOKEN_URL,
    AnthropicTokenRefresher,
)

FIXTURES = Path(__file__).parent.parent / "domain" / "fixtures"


def load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class TestRefresherIsATokenRefresherPort:
    """AnthropicTokenRefresher explicitly subclasses the port (greppable map)."""

    def test_is_a_token_refresher_port(self):
        assert isinstance(AnthropicTokenRefresher(FakeHttpTransport()), TokenRefresherPort)


class TestRefreshSendsTheRightRequest:
    """The exact POST the RFC 6749 refresh grant sends."""

    def test_posts_the_rfc6749_grant_with_two_headers(self):
        # arrange
        transport = FakeHttpTransport(
            response=HttpResponse(status=200, body=b'{"access_token": "a", "expires_in": 3600}')
        )
        refresher = AnthropicTokenRefresher(transport)

        # act
        refresher.refresh("rt-current")

        # assert — no anthropic-beta on the refresh POST
        [(method, url, headers, body, timeout_s)] = transport.requests
        assert method == "POST"
        assert url == TOKEN_URL
        assert headers == {
            "Content-Type": "application/json",
            "User-Agent": "claude-acc-manager/0.1.0",
        }
        assert body is not None
        assert json.loads(body) == {
            "grant_type": "refresh_token",
            "refresh_token": "rt-current",
            "client_id": OAUTH_CLIENT_ID,
        }
        assert timeout_s == 10.0


class TestRefreshParsesSuccess:
    """A 200 response yields the rotated token pair."""

    def test_rotated_pair_is_returned(self):
        # arrange
        body = b'{"access_token": "new-at", "refresh_token": "new-rt", "expires_in": 3600}'
        refresher = AnthropicTokenRefresher(
            FakeHttpTransport(response=HttpResponse(status=200, body=body))
        )

        # act
        rotated = refresher.refresh("old-rt")

        # assert
        assert rotated.access_token == "new-at"
        assert rotated.refresh_token == "new-rt"
        assert rotated.expires_in_s == 3600.0

    def test_absent_refresh_token_is_none_so_the_caller_keeps_the_old_one(self):
        # arrange — the stored refresh token is only overwritten when the
        # server rotated it
        body = b'{"access_token": "new-at", "expires_in": 3600}'
        refresher = AnthropicTokenRefresher(
            FakeHttpTransport(response=HttpResponse(status=200, body=body))
        )

        # act
        rotated = refresher.refresh("old-rt")

        # assert
        assert rotated.refresh_token is None

    def test_blank_rotated_refresh_token_counts_as_absent(self):
        # arrange
        body = b'{"access_token": "new-at", "refresh_token": "   ", "expires_in": 3600}'
        refresher = AnthropicTokenRefresher(
            FakeHttpTransport(response=HttpResponse(status=200, body=body))
        )

        # act / assert
        assert refresher.refresh("old-rt").refresh_token is None

    def test_integral_float_expires_in_is_accepted(self):
        # arrange — an integral-float expires_in is valid
        body = b'{"access_token": "new-at", "expires_in": 3600.0}'
        refresher = AnthropicTokenRefresher(
            FakeHttpTransport(response=HttpResponse(status=200, body=body))
        )

        # act / assert
        assert refresher.refresh("old-rt").expires_in_s == 3600.0


class TestRefreshRejectsMalformedSuccess:
    """A 200 whose body is not a usable token pair is schema drift, not a token.

    Each malformed shape names the offending field and expected type in the
    error (AGENTS.md) — never the value, which on this endpoint can be the
    secret itself (docs/architecture.md §8).
    """

    def _refresher(self, body: bytes) -> AnthropicTokenRefresher:
        return AnthropicTokenRefresher(
            FakeHttpTransport(response=HttpResponse(status=200, body=body))
        )

    @pytest.mark.parametrize(
        "body",
        [
            b'{"expires_in": 3600}',  # no access_token
            b'{"access_token": "", "expires_in": 3600}',  # empty access_token
            b'{"access_token": 123, "expires_in": 3600}',  # non-string
        ],
    )
    def test_missing_access_token_names_that_field(self, body: bytes):
        with pytest.raises(ValueError) as exc_info:
            self._refresher(body).refresh("old-rt")
        assert (
            str(exc_info.value)
            == "token refresh response field 'access_token' is missing or not a string"
        )

    @pytest.mark.parametrize(
        ("body", "kind"),
        [
            (b'{"access_token": "a"}', "NoneType"),
            (b'{"access_token": "a", "expires_in": "soon"}', "str"),
            (b'{"access_token": "a", "expires_in": true}', "bool"),
        ],
    )
    def test_bad_expires_in_names_that_field_and_its_type(self, body: bytes, kind: str):
        with pytest.raises(ValueError) as exc_info:
            self._refresher(body).refresh("old-rt")
        assert str(exc_info.value) == (
            f"token refresh response field 'expires_in' is {kind}, expected a number"
        )

    def test_non_json_body_is_named_as_such(self):
        with pytest.raises(ValueError) as exc_info:
            self._refresher(b"not json").refresh("old-rt")
        assert str(exc_info.value) == "token refresh response was not valid JSON"

    def test_json_array_body_names_the_type(self):
        with pytest.raises(ValueError) as exc_info:
            self._refresher(b"[1, 2, 3]").refresh("old-rt")
        assert str(exc_info.value) == ("token refresh response was list, expected a JSON object")

    def test_the_offending_body_value_is_never_in_the_message(self):
        # arrange — the malformed access_token value is itself token-shaped
        secret = "sk-ant-oat01-leaked"
        body = json.dumps({"access_token": secret, "expires_in": "bad"}).encode()

        # act
        with pytest.raises(ValueError) as exc_info:
            self._refresher(body).refresh("old-rt")

        # assert
        assert secret not in str(exc_info.value)


class TestRefreshRaisesOnError:
    """Non-2xx raises AnthropicApiError; invalid_grant is classified for the caller."""

    def test_invalid_grant_is_surfaced_as_the_error_code(self):
        # arrange
        body = b'{"error": "invalid_grant", "error_description": "expired"}'
        refresher = AnthropicTokenRefresher(
            FakeHttpTransport(response=HttpResponse(status=400, body=body))
        )

        # act / assert
        with pytest.raises(AnthropicApiError) as exc_info:
            refresher.refresh("dead-rt")
        assert exc_info.value.status == 400
        assert exc_info.value.error_code == "invalid_grant"

    def test_network_failure_propagates(self):
        refresher = AnthropicTokenRefresher(
            FakeHttpTransport(error=HttpTransportError("connection refused"))
        )
        with pytest.raises(HttpTransportError):
            refresher.refresh("rt")

    def test_error_body_never_reaches_the_exception(self):
        # arrange
        secret = "rt-super-secret-value"
        body = json.dumps({"error": "invalid_grant", "leaked": secret}).encode()
        refresher = AnthropicTokenRefresher(
            FakeHttpTransport(response=HttpResponse(status=403, body=body))
        )

        # act
        with pytest.raises(AnthropicApiError) as exc_info:
            refresher.refresh("rt")

        # assert
        assert secret not in str(exc_info.value)
        assert secret not in repr(exc_info.value)
