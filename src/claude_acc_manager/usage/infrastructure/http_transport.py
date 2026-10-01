"""HttpTransportPort over urllib — the stdlib client, no runtime dependency.

AGENTS.md: "wrap third-party libs behind a thin interface owned by this
project"; ADR-0002 locks stdlib ``urllib`` for HTTP. A non-2xx response is
still a real response (``HttpResponse``) — only a transport-level failure
(timeout, DNS, connection refused) raises ``HttpTransportError``; interpreting
the status code is the caller's job (usage/infrastructure/anthropic_oauth.py).

Example:
    transport = UrllibHttpTransport()
    response = transport.request("GET", url, headers, None, timeout_s=5.0)
"""

import urllib.error
import urllib.request
from collections.abc import Mapping

from claude_acc_manager.usage.application.ports import HttpResponse, HttpTransportError


class UrllibHttpTransport:
    """HttpTransportPort implemented with urllib.request.

    Example:
        UrllibHttpTransport().request("GET", url, {}, None, timeout_s=5.0)
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
        """Perform one HTTP request; raises HttpTransportError on network failure."""
        req = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
        try:
            # B310 (audit_url_open): *url* is always one of this project's own
            # hardcoded https://api.anthropic.com / https://platform.claude.com
            # constants (usage/infrastructure/anthropic_oauth.py, guarded by
            # _require_allowed_host), never caller input.
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # nosec B310
                return HttpResponse(status=resp.status, body=resp.read())
        except urllib.error.HTTPError as exc:
            return HttpResponse(status=exc.code, body=exc.read())
        except urllib.error.URLError as exc:
            raise HttpTransportError(str(exc.reason)) from exc
        except TimeoutError as exc:
            raise HttpTransportError("timed out") from exc
