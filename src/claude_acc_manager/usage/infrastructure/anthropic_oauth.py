"""Anthropic's undocumented OAuth endpoints: usage, token refresh, profile.

Evidence for every constant below is claude-swap ``oauth.py``, read directly
and cross-checked against its own git history — not the plan's summary table,
which turned out to flatten two real discrepancies:

- **User-Agent**: the plan claimed both reference repos spoof
  ``claude-code/<version>``. Only ai-usagebar does. claude-swap sends its own
  honest ``claude-swap/1.0`` — confirmed by ``git log -S"User-Agent"``: commit
  ``ee2563c`` ("fix oauth refresh 403 by adding User-Agent header",
  2026-04-03) added that exact literal to both the usage GET and the refresh
  POST in one change, fixing a real measured 403, and it has run unchanged in
  production since. claude-swap's own ``usage_store.py:120-126`` documents the
  result: *"The usage endpoint enforces a request budget on non-first-party
  User-Agents"* — i.e. claude-swap knowingly lives inside the smaller
  third-party budget rather than spoofing, and the ``poll_policy.py`` budget
  numbers this project's own plan already adopted (SERVE_TTL_S=180,
  MIN_INTERVAL_S=180, ~28-30 req/h) were measured *under that regime*.
  Spoofing here would invalidate the budget evidence this project already
  committed to, so ``cam`` sends its own honest UA too.
- **Headers are per-endpoint, not uniform**: claude-swap sends three
  different header sets — usage GET has no ``Content-Type`` (no body to
  describe), the refresh POST has no ``anthropic-beta``, and the profile GET
  has no ``anthropic-beta`` either. Each function below sends exactly the set
  its claude-swap counterpart does, not a superset.

Example:
    api = AnthropicUsageApi(UrllibHttpTransport())
    snapshot = api.fetch_usage(access_token)
"""

import json
from typing import cast
from urllib.parse import urlparse

from claude_acc_manager.usage.application.ports import (
    AnthropicApiError,
    HttpTransportPort,
    UsageApiPort,
)
from claude_acc_manager.usage.domain.usage_snapshot import (
    UsageSnapshot,
    usage_snapshot_from_response,
)

# See module docstring: an honest identifier, matching claude-swap's proven
# approach — not ai-usagebar's claude-code spoof. Pinned literal (not read
# from packaging metadata) mirrors both reference repos' own practice: one
# greppable point of change, no metadata-lookup fragility in tests.
USER_AGENT = "claude-acc-manager/0.1.0"

OAUTH_BETA_HEADER = "oauth-2025-04-20"
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
PROFILE_URL = "https://api.anthropic.com/api/oauth/profile"

# Plan §5.1: network egress only to these two hosts, no configurable base
# URLs. The three URLs above are hardcoded constants, so this is
# defense-in-depth against a future edit rather than a live routing table.
_ALLOWED_HOSTS = frozenset({"api.anthropic.com", "platform.claude.com"})

_USAGE_TIMEOUT_S = 5.0


def _require_allowed_host(url: str) -> None:
    """Raise ValueError unless *url*'s host is in the Anthropic allowlist.

    Example:
        _require_allowed_host("https://api.anthropic.com/api/oauth/usage")
    """
    host = urlparse(url).hostname
    if host not in _ALLOWED_HOSTS:
        raise ValueError(
            f"refusing to contact host {host!r} from url {url!r}; "
            f"only {sorted(_ALLOWED_HOSTS)} are permitted"
        )


def _parse_error_code(body: bytes) -> str | None:
    """The RFC 6749 top-level ``error`` field of a JSON error body, or None.

    Never returns the body itself — only this one classified, short code
    (plan §5.4 redaction guarantee).
    """
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    # cast() is a runtime no-op — its type argument is type-checker-only, so
    # mutants of it are equivalent by construction (same reason
    # accounts/domain/oauth_identity.py carries this pragma).
    fields = cast("dict[str, object]", parsed)  # pragma: no mutate
    error = fields.get("error")
    return error if isinstance(error, str) else None


class AnthropicUsageApi(UsageApiPort):
    """UsageApiPort over ``GET /api/oauth/usage`` (claude-swap oauth.py request_usage_data).

    Example:
        AnthropicUsageApi(UrllibHttpTransport()).fetch_usage(access_token)
    """

    def __init__(self, transport: HttpTransportPort) -> None:
        """Inject the HTTP transport (test seam: FakeHttpTransport)."""
        self._transport = transport

    def fetch_usage(self, access_token: str) -> UsageSnapshot:
        """Raises AnthropicApiError on non-2xx, HttpTransportError on network failure."""
        _require_allowed_host(USAGE_URL)
        headers = {
            "Authorization": f"Bearer {access_token}",
            "anthropic-beta": OAUTH_BETA_HEADER,
            "User-Agent": USER_AGENT,
        }
        response = self._transport.request(
            "GET", USAGE_URL, headers, None, timeout_s=_USAGE_TIMEOUT_S
        )
        if response.status // 100 != 2:
            raise AnthropicApiError(response.status, _parse_error_code(response.body))
        return usage_snapshot_from_response(json.loads(response.body))
