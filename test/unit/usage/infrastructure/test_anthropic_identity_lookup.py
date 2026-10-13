"""``AnthropicIdentityLookup`` — the profile endpoint's wire contract.

Header sets, URL, timeouts, and the ``_require_allowed_host`` allowlist are
pinned exactly — this endpoint gets its own minimal header set, not a
uniform one (ADR-0007).
"""

import json
from pathlib import Path

import pytest
from support.fake_http_transport import FakeHttpTransport

from claude_acc_manager.usage.application.ports import (
    HttpResponse,
    HttpTransportError,
    IdentityLookupPort,
)
from claude_acc_manager.usage.domain.resolved_identity import ResolvedIdentity
from claude_acc_manager.usage.infrastructure.anthropic_oauth import (
    PROFILE_URL,
    USAGE_URL,
    AnthropicIdentityLookup,
    _require_allowed_host,
)

FIXTURES = Path(__file__).parent.parent / "domain" / "fixtures"


def load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


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
