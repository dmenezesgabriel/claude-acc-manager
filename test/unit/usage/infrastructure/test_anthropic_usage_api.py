"""``AnthropicUsageApi`` — the usage endpoint's wire contract.

Header sets, URL, and timeouts are pinned exactly — this endpoint gets its
own minimal header set, not a uniform one (ADR-0007). Error bodies are
redacted so token-shaped text never reaches the exception message.
"""

import json
from pathlib import Path

import pytest
from support.fake_http_transport import FakeHttpTransport

from claude_acc_manager.usage.application.ports import (
    AnthropicApiError,
    HttpResponse,
    HttpTransportError,
    UsageApiPort,
)
from claude_acc_manager.usage.infrastructure.anthropic_oauth import (
    USAGE_URL,
    AnthropicUsageApi,
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
