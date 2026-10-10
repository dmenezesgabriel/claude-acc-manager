"""Unit tests for update.infrastructure.pypi_release_feed and the
ReleaseFeedPort it implements."""

import pytest
from support.fake_http_transport import FakeHttpTransport

from claude_acc_manager import package_version
from claude_acc_manager.update.application.ports import ReleaseFeedPort
from claude_acc_manager.update.infrastructure.pypi_release_feed import PyPiReleaseFeed
from claude_acc_manager.usage.application.ports import HttpResponse, HttpTransportError


def make_feed(
    *, response: HttpResponse | None = None, error: HttpTransportError | None = None
) -> tuple[PyPiReleaseFeed, FakeHttpTransport]:
    transport = FakeHttpTransport(response=response, error=error)
    return PyPiReleaseFeed(transport), transport


class TestPyPiReleaseFeedAdaptsThePort:
    def test_is_a_release_feed_port(self):
        assert isinstance(PyPiReleaseFeed(FakeHttpTransport()), ReleaseFeedPort)


class TestLatestVersionSendsTheRightRequest:
    def test_gets_the_pypi_json_document_with_a_tight_timeout(self):
        # arrange
        feed, transport = make_feed(
            response=HttpResponse(status=200, body=b'{"info": {"version": "1.2.3"}}')
        )

        # act
        feed.latest_version()

        # assert
        [(method, url, headers, body, timeout_s)] = transport.requests
        assert method == "GET"
        assert url == "https://pypi.org/pypi/claude-acc-manager/json"
        assert headers == {"User-Agent": f"claude-acc-manager/{package_version()}"}
        assert body is None
        assert timeout_s == 2.0


class TestLatestVersionParsesSuccess:
    def test_returns_the_info_version(self):
        # arrange
        feed, _ = make_feed(
            response=HttpResponse(status=200, body=b'{"info": {"version": "9.9.9"}}')
        )

        # act / assert
        assert feed.latest_version() == "9.9.9"

    @pytest.mark.parametrize("status", [201, 299])
    def test_any_2xx_status_counts_as_success(self, status: int):
        # the contract is the 2xx band (status // 100), not 200 alone —
        # for /-division equivalents, statuses like 299 distinguish them
        # arrange
        feed, _ = make_feed(
            response=HttpResponse(status=status, body=b'{"info": {"version": "9.9.9"}}')
        )

        # act / assert
        assert feed.latest_version() == "9.9.9"


class TestLatestVersionNeverRaises:
    """Port contract: the check is advisory — every failure is a quiet None."""

    def test_a_transport_error_returns_none(self):
        # arrange
        feed, _ = make_feed(error=HttpTransportError("no route"))

        # act / assert
        assert feed.latest_version() is None

    @pytest.mark.parametrize("status", [404, 500, 503])
    def test_a_non_2xx_status_returns_none(self, status: int):
        # arrange
        feed, _ = make_feed(response=HttpResponse(status=status, body=b"{}"))

        # act / assert
        assert feed.latest_version() is None

    @pytest.mark.parametrize(
        "body",
        [
            b"not json",
            b"\xff\xfe invalid utf-8",
            b"[1, 2]",
            b"{}",
            b'{"info": null}',
            b'{"info": "a string"}',
            b'{"info": {}}',
            b'{"info": {"version": 1}}',
            b'{"info": {"version": ""}}',
            b'{"info": {"version": "   "}}',
        ],
    )
    def test_a_body_without_a_release_version_returns_none(self, body: bytes):
        # arrange
        feed, _ = make_feed(response=HttpResponse(status=200, body=body))

        # act / assert
        assert feed.latest_version() is None
