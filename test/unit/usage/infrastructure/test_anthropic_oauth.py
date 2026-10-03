"""Unit tests for usage.infrastructure.anthropic_oauth.

Header sets, URLs, and timeouts are pinned exactly — each endpoint gets its
OWN minimal header set, not a uniform one (ADR-0007; docs/architecture.md
§3).
"""

import json
from pathlib import Path

import pytest
from support.fake_http_transport import FakeHttpTransport

from claude_acc_manager.usage.application.ports import (
    AnthropicApiError,
    HttpResponse,
    HttpTransportError,
    IdentityLookupPort,
    TokenRefresherPort,
    UsageApiPort,
)
from claude_acc_manager.usage.domain.resolved_identity import ResolvedIdentity
from claude_acc_manager.usage.infrastructure.anthropic_oauth import (
    OAUTH_CLIENT_ID,
    PROFILE_URL,
    TOKEN_URL,
    USAGE_URL,
    AnthropicIdentityLookup,
    AnthropicTokenRefresher,
    AnthropicUsageApi,
    _require_allowed_host,
)

FIXTURES = Path(__file__).parent.parent / "domain" / "fixtures"


def load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class TestAnthropicUsageApiIsAUsageApiPort:
    """AnthropicUsageApi explicitly subclasses the port (greppable map)."""

    def test_is_a_usage_api_port(self):
        # arrange / act
        api = AnthropicUsageApi(FakeHttpTransport())

        # assert
        assert isinstance(api, UsageApiPort)


class TestFetchUsageSendsTheRightRequest:
    """The exact GET, URL, and header set the usage request sends."""

    def test_sends_get_with_the_three_headers_usage_needs(self):
        # arrange
        transport = FakeHttpTransport(
            response=HttpResponse(status=200, body=b'{"five_hour": {"utilization": 1.0}}')
        )
        api = AnthropicUsageApi(transport)

        # act
        api.fetch_usage("tok-access-live")

        # assert
        [(method, url, headers, body, timeout_s)] = transport.requests
        assert method == "GET"
        assert url == USAGE_URL
        assert headers == {
            "Authorization": "Bearer tok-access-live",
            "anthropic-beta": "oauth-2025-04-20",
            "User-Agent": "claude-acc-manager/0.1.0",
        }
        assert body is None
        assert timeout_s == 5.0


class TestFetchUsageParsesSuccess:
    """A 200 response is parsed into a UsageSnapshot."""

    def test_parses_the_full_fixture(self):
        # arrange
        data = load_fixture("usage_response_full.json")
        transport = FakeHttpTransport(
            response=HttpResponse(status=200, body=json.dumps(data).encode())
        )
        api = AnthropicUsageApi(transport)

        # act
        snapshot = api.fetch_usage("tok")

        # assert
        assert snapshot.five_hour is not None
        assert snapshot.five_hour.pct == 62.0
        assert snapshot.scoped[0].name == "Fable"

    def test_parses_the_minimal_fixture(self):
        # arrange
        data = load_fixture("usage_response_minimal.json")
        transport = FakeHttpTransport(
            response=HttpResponse(status=200, body=json.dumps(data).encode())
        )
        api = AnthropicUsageApi(transport)

        # act
        snapshot = api.fetch_usage("tok")

        # assert
        assert snapshot.five_hour is not None
        assert snapshot.five_hour.pct == 15.0
        assert snapshot.scoped == ()


class TestFetchUsageRaisesOnError:
    """Non-2xx responses raise AnthropicApiError with the classified error code."""

    @pytest.mark.parametrize("status", [401, 403, 429])
    def test_non_2xx_raises_anthropic_api_error(self, status: int):
        # arrange
        transport = FakeHttpTransport(response=HttpResponse(status=status, body=b"{}"))
        api = AnthropicUsageApi(transport)

        # act / assert
        with pytest.raises(AnthropicApiError) as exc_info:
            api.fetch_usage("tok")
        assert exc_info.value.status == status
        assert str(status) in str(exc_info.value)

    def test_204_is_still_a_success_not_an_error(self):
        # arrange — pins integer status-class division: 204 // 100 == 2 (a
        # real 2xx), whereas float division (204 / 100 == 2.04) would
        # wrongly treat it as an error
        transport = FakeHttpTransport(
            response=HttpResponse(status=204, body=b'{"five_hour": {"utilization": 1.0}}')
        )
        api = AnthropicUsageApi(transport)

        # act / assert — must not raise
        api.fetch_usage("tok")

    def test_error_body_error_field_is_classified(self):
        # arrange
        body = b'{"error": "invalid_grant"}'
        transport = FakeHttpTransport(response=HttpResponse(status=400, body=body))
        api = AnthropicUsageApi(transport)

        # act / assert
        with pytest.raises(AnthropicApiError) as exc_info:
            api.fetch_usage("tok")
        assert exc_info.value.error_code == "invalid_grant"

    def test_unparseable_body_has_no_error_code(self):
        # arrange
        transport = FakeHttpTransport(response=HttpResponse(status=500, body=b"not json"))
        api = AnthropicUsageApi(transport)

        # act / assert
        with pytest.raises(AnthropicApiError) as exc_info:
            api.fetch_usage("tok")
        assert exc_info.value.error_code is None

    def test_json_body_that_is_not_an_object_has_no_error_code(self):
        # arrange — valid JSON, but an array rather than an object
        transport = FakeHttpTransport(response=HttpResponse(status=500, body=b"[1, 2, 3]"))
        api = AnthropicUsageApi(transport)

        # act / assert
        with pytest.raises(AnthropicApiError) as exc_info:
            api.fetch_usage("tok")
        assert exc_info.value.error_code is None

    def test_a_non_string_error_field_is_no_code(self):
        # arrange — the RFC 6749 code must be a string to classify; anything
        # else is dropped rather than surfaced
        transport = FakeHttpTransport(response=HttpResponse(status=400, body=b'{"error": 123}'))
        api = AnthropicUsageApi(transport)

        # act / assert
        with pytest.raises(AnthropicApiError) as exc_info:
            api.fetch_usage("tok")
        assert exc_info.value.error_code is None

    def test_network_failure_propagates_as_http_transport_error(self):
        # arrange
        transport = FakeHttpTransport(error=HttpTransportError("connection refused"))
        api = AnthropicUsageApi(transport)

        # act / assert
        with pytest.raises(HttpTransportError):
            api.fetch_usage("tok")


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


class TestRedaction:
    """A token-shaped body never reaches the exception's message."""

    def test_error_body_text_never_reaches_the_exception_message(self):
        # arrange — an echoed access token embedded in the raw body
        secret = "sk-ant-oat01-super-secret-token"
        body = json.dumps({"error": "invalid_grant", "leaked": secret}).encode()
        transport = FakeHttpTransport(response=HttpResponse(status=400, body=body))
        api = AnthropicUsageApi(transport)

        # act
        with pytest.raises(AnthropicApiError) as exc_info:
            api.fetch_usage("tok")

        # assert
        assert secret not in str(exc_info.value)
        assert secret not in repr(exc_info.value)


class TestIdentityLookupIsAnIdentityLookupPort:
    """AnthropicIdentityLookup explicitly subclasses the port (greppable map)."""

    def test_is_an_identity_lookup_port(self):
        assert isinstance(AnthropicIdentityLookup(FakeHttpTransport()), IdentityLookupPort)


class TestResolveSendsTheRightRequest:
    """The exact GET the profile endpoint needs (no anthropic-beta)."""

    def test_sends_get_with_the_three_headers_profile_needs(self):
        # arrange
        body = b'{"account": {"uuid": "acc-1"}}'
        lookup = AnthropicIdentityLookup(
            FakeHttpTransport(response=HttpResponse(status=200, body=body))
        )

        # act
        lookup.resolve("tok-access")

        # assert
        [(method, url, headers, req_body, timeout_s)] = lookup._transport.requests  # type: ignore[attr-defined]
        assert method == "GET"
        assert url == PROFILE_URL
        assert headers == {
            "Authorization": "Bearer tok-access",
            "Content-Type": "application/json",
            "User-Agent": "claude-acc-manager/0.1.0",
        }
        assert req_body is None
        assert timeout_s == 5.0


class TestResolveParsesSuccess:
    """A 200 with a usable account.uuid resolves to a ResolvedIdentity."""

    def test_resolves_the_identity(self):
        # arrange
        body = json.dumps(
            {
                "account": {"uuid": "acc-1", "email": "user@example.com"},
                "organization": {"uuid": "org-9"},
            }
        ).encode()
        lookup = AnthropicIdentityLookup(
            FakeHttpTransport(response=HttpResponse(status=200, body=body))
        )

        # act
        identity = lookup.resolve("tok")

        # assert
        assert identity == ResolvedIdentity(
            account_uuid="acc-1", email="user@example.com", organization_uuid="org-9"
        )

    def test_any_2xx_status_is_treated_as_success(self):
        # arrange — pins integer status-class division (202 // 100 == 2),
        # not float (202 / 100 == 2.02 would fail open to None)
        body = b'{"account": {"uuid": "acc-1"}}'
        lookup = AnthropicIdentityLookup(
            FakeHttpTransport(response=HttpResponse(status=202, body=body))
        )

        # act / assert
        assert lookup.resolve("tok") == ResolvedIdentity(
            account_uuid="acc-1", email=None, organization_uuid=None
        )


class TestResolveFailsOpenToNone:
    """Every failure mode returns None — the oracle is advisory, never raises."""

    def test_body_without_a_usable_uuid_is_none(self):
        lookup = AnthropicIdentityLookup(
            FakeHttpTransport(response=HttpResponse(status=200, body=b'{"account": {}}'))
        )
        assert lookup.resolve("tok") is None

    def test_non_json_body_is_none(self):
        lookup = AnthropicIdentityLookup(
            FakeHttpTransport(response=HttpResponse(status=200, body=b"not json"))
        )
        assert lookup.resolve("tok") is None

    def test_json_array_body_is_none(self):
        lookup = AnthropicIdentityLookup(
            FakeHttpTransport(response=HttpResponse(status=200, body=b"[1, 2, 3]"))
        )
        assert lookup.resolve("tok") is None

    @pytest.mark.parametrize("status", [401, 403, 429, 500])
    def test_non_2xx_is_none_not_an_error(self, status: int):
        lookup = AnthropicIdentityLookup(
            FakeHttpTransport(response=HttpResponse(status=status, body=b"{}"))
        )
        assert lookup.resolve("tok") is None

    def test_network_failure_is_none_not_an_error(self):
        lookup = AnthropicIdentityLookup(
            FakeHttpTransport(error=HttpTransportError("connection refused"))
        )
        assert lookup.resolve("tok") is None


class TestAllowlist:
    """Only api.anthropic.com and platform.claude.com are ever contacted."""

    def test_accepts_the_real_usage_url(self):
        _require_allowed_host(USAGE_URL)  # must not raise

    def test_rejects_any_other_host(self):
        with pytest.raises(ValueError, match="evil.example.com"):
            _require_allowed_host("https://evil.example.com/api/oauth/usage")
