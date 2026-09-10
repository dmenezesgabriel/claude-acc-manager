"""HttpTransportPort fake that records requests and replays a scripted answer."""

from collections.abc import Mapping

from claude_acc_manager.usage.application.ports import (
    HttpResponse,
    HttpTransportError,
    HttpTransportPort,
)


class FakeHttpTransport(HttpTransportPort):
    """Returns one pinned HttpResponse (or raises one pinned error) every call.

    Records every request it receives so tests can assert what was sent.
    """

    def __init__(
        self,
        *,
        response: HttpResponse | None = None,
        error: HttpTransportError | None = None,
    ) -> None:
        """Pin the outcome — an HttpResponse to return, or an error to raise."""
        self._response = response
        self._error = error
        self.requests: list[tuple[str, str, Mapping[str, str], bytes | None, float]] = []

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        *,
        timeout_s: float,
    ) -> HttpResponse:
        """Record the call, then replay the pinned response or error."""
        self.requests.append((method, url, headers, body, timeout_s))
        if self._error is not None:
            raise self._error
        assert self._response is not None, "FakeHttpTransport has no scripted response"
        return self._response
