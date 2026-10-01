"""Unit tests for usage.infrastructure.http_transport.

Tests the real urllib-backed adapter against a real, local, loopback HTTP
server (matching this codebase's own convention — file_lock.py, fsio.py, and
claude_login_launcher.py all test the real mechanism against a real,
controlled stand-in, never `unittest.mock` on a stdlib call). Loopback-only:
no real network egress, matching the hermeticity invariant in
docs/architecture.md §10.
"""

import time
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest

from claude_acc_manager.usage.application.ports import HttpTransportError
from claude_acc_manager.usage.infrastructure.http_transport import UrllibHttpTransport


class _ScriptedServer(HTTPServer):
    """An HTTPServer that answers every request with one scripted response."""

    response_status = 200
    response_body = b""
    response_delay_s = 0.0
    last_request: dict[str, object] | None = None


class _RecordingHandler(BaseHTTPRequestHandler):
    """Records the request it received and answers with the server's script."""

    server: _ScriptedServer

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        self.server.last_request = {
            "method": self.command,
            "path": self.path,
            "headers": dict(self.headers.items()),
            "body": self.rfile.read(length) if length else b"",
        }
        if self.server.response_delay_s:
            time.sleep(self.server.response_delay_s)
        self.send_response(self.server.response_status)
        self.end_headers()
        self.wfile.write(self.server.response_body)

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler's own naming
        self._handle()

    def do_POST(self) -> None:  # noqa: N802
        self._handle()

    def do_DELETE(self) -> None:  # noqa: N802
        self._handle()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Silence the default stderr access log — tests assert state, not logs."""


@pytest.fixture
def local_server() -> Generator[_ScriptedServer]:
    """A loopback HTTP server on an OS-assigned port, torn down after the test."""
    server = _ScriptedServer(("127.0.0.1", 0), _RecordingHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def base_url(server: _ScriptedServer) -> str:
    host, port = server.server_address[0], server.server_address[1]
    return f"http://{host}:{port}"


class TestRequestSucceeds:
    """A 2xx (or any real HTTP) response comes back as an HttpResponse."""

    def test_returns_status_and_body(self, local_server: _ScriptedServer):
        # arrange
        local_server.response_status = 200
        local_server.response_body = b'{"ok": true}'
        transport = UrllibHttpTransport()

        # act
        response = transport.request("GET", base_url(local_server) + "/x", {}, None, timeout_s=5.0)

        # assert
        assert response.status == 200
        assert response.body == b'{"ok": true}'

    def test_sends_method_headers_and_body(self, local_server: _ScriptedServer):
        # arrange
        transport = UrllibHttpTransport()

        # act
        transport.request(
            "POST",
            base_url(local_server) + "/token",
            {"Authorization": "Bearer tok", "Content-Type": "application/json"},
            b'{"grant_type": "refresh_token"}',
            timeout_s=5.0,
        )

        # assert
        received = local_server.last_request
        assert received is not None
        assert received["method"] == "POST"
        assert received["path"] == "/token"
        headers = received["headers"]
        assert isinstance(headers, dict)
        assert headers["Authorization"] == "Bearer tok"
        assert received["body"] == b'{"grant_type": "refresh_token"}'

    def test_sends_the_exact_method_given(self, local_server: _ScriptedServer):
        # arrange — no body, so urllib's own data-presence default would be
        # GET; only passing *method* through explicitly makes this DELETE
        transport = UrllibHttpTransport()

        # act
        transport.request("DELETE", base_url(local_server) + "/x", {}, None, timeout_s=5.0)

        # assert
        received = local_server.last_request
        assert received is not None
        assert received["method"] == "DELETE"

    def test_non_2xx_status_is_still_an_http_response_not_an_error(
        self, local_server: _ScriptedServer
    ):
        # arrange — the transport never interprets status; that is the caller's job
        local_server.response_status = 429
        local_server.response_body = b'{"error": "rate_limited"}'
        transport = UrllibHttpTransport()

        # act
        response = transport.request("GET", base_url(local_server) + "/x", {}, None, timeout_s=5.0)

        # assert
        assert response.status == 429
        assert response.body == b'{"error": "rate_limited"}'


class TestTransportFailure:
    """A request that never reaches (or never finishes with) a server raises
    HttpTransportError, carrying a non-empty reason."""

    def test_connection_refused_raises_transport_error(self):
        # arrange — nothing listens on this loopback port
        transport = UrllibHttpTransport()

        # act
        with pytest.raises(HttpTransportError) as exc_info:
            transport.request("GET", "http://127.0.0.1:1/x", {}, None, timeout_s=1.0)

        # assert
        assert "refused" in str(exc_info.value).lower()

    def test_read_timeout_raises_transport_error(self, local_server: _ScriptedServer):
        # arrange — the connection succeeds, but the response never arrives
        # in time (a bare TimeoutError, distinct from connection-refused's
        # URLError — both are observed in practice, claude-swap oauth.py
        # _classify_usage_error handles both as separate cases)
        local_server.response_delay_s = 0.5
        transport = UrllibHttpTransport()

        # act
        with pytest.raises(HttpTransportError) as exc_info:
            transport.request("GET", base_url(local_server) + "/x", {}, None, timeout_s=0.05)

        # assert
        assert str(exc_info.value) == "timed out"
