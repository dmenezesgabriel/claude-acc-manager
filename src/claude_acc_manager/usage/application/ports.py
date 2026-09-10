"""Ports of the usage component — the single map of every boundary."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class HttpResponse:
    """One HTTP response: status code and raw body.

    No headers field yet — nothing in this milestone reads one (a future
    ``Retry-After`` need, e.g. the M5/M9 poll policy, can add it without
    breaking this port).

    Example:
        HttpResponse(status=200, body=b'{"five_hour": {"utilization": 62.0}}')
    """

    status: int
    body: bytes


class HttpTransportError(Exception):
    """A request never reached a server: timeout, DNS failure, connection refused.

    A real HTTP response, even 4xx/5xx, is never this — it is an
    :class:`HttpResponse`. Only a transport-level failure raises.
    """


@runtime_checkable
class HttpTransportPort(Protocol):
    """Boundary over the HTTP client this tool talks to Anthropic through.

    AGENTS.md: "wrap third-party libs behind a thin interface owned by this
    project" — this is that interface for stdlib ``urllib`` (plan §3: no
    runtime HTTP dependency), and the seam that lets the Anthropic adapters
    be tested without a socket.

    Example:
        response = transport.request("GET", url, headers, None, timeout_s=5.0)
    """

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        *,
        timeout_s: float,
    ) -> HttpResponse:
        """Perform one HTTP request.

        Raises HttpTransportError when no response was received at all.
        """
        ...
