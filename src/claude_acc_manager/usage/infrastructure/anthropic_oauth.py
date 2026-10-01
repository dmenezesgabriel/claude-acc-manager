"""Anthropic's undocumented OAuth endpoints: usage, token refresh, profile.

Evidence for every constant below is claude-swap ``oauth.py``, read directly
and cross-checked against its own git history — see ADR-0007 for the decision
this produced and its correction of an earlier flattened reading:

- **User-Agent**: an earlier plan revision claimed both reference repos spoof
  ``claude-code/<version>``. Only ai-usagebar does. claude-swap sends its own
  honest ``claude-swap/1.0`` — confirmed by ``git log -S"User-Agent"``: commit
  ``ee2563c`` ("fix oauth refresh 403 by adding User-Agent header",
  2026-04-03) added that exact literal to both the usage GET and the refresh
  POST in one change, fixing a real measured 403, and it has run unchanged in
  production since. claude-swap's own ``usage_store.py:120-126`` documents the
  result: *"The usage endpoint enforces a request budget on non-first-party
  User-Agents"* — i.e. claude-swap knowingly lives inside the smaller
  third-party budget rather than spoofing, and the ``poll_policy.py`` budget
  numbers this project's polling already adopted (SERVE_TTL_S=180,
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
    HttpResponse,
    HttpTransportError,
    HttpTransportPort,
    IdentityLookupPort,
    RefreshedTokens,
    TokenRefresherPort,
    UsageApiPort,
)
from claude_acc_manager.usage.domain.resolved_identity import (
    ResolvedIdentity,
    resolved_identity_from_profile_response,
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
_REFRESH_TIMEOUT_S = 10.0
_PROFILE_TIMEOUT_S = 5.0


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


def _json_object_or_none(body: bytes) -> dict[str, object] | None:
    """Parse *body* as a JSON object, tolerantly — None for anything else.

    cast() is a runtime no-op — its type argument is type-checker-only, so
    mutants of it are equivalent by construction (same reason
    accounts/domain/oauth_identity.py carries this pragma).
    """
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return cast("dict[str, object]", parsed)  # pragma: no mutate


def _parse_error_code(body: bytes) -> str | None:
    """The RFC 6749 top-level ``error`` field of a JSON error body, or None.

    Never returns the body itself — only this one classified, short code
    (docs/architecture.md §8 redaction guarantee).
    """
    fields = _json_object_or_none(body)
    if fields is None:
        return None
    error = fields.get("error")
    return error if isinstance(error, str) else None


def _raise_for_status(response: HttpResponse) -> None:
    """Raise AnthropicApiError (status + classified code only) unless 2xx."""
    if response.status // 100 != 2:
        raise AnthropicApiError(response.status, _parse_error_code(response.body))


def _success_object(body: bytes, context: str) -> dict[str, object]:
    """Parse a 2xx JSON body as an object, or raise ValueError naming *context*.

    The offending value is never echoed — the body of a token endpoint can
    itself be the secret (docs/architecture.md §8). Only the shape and *context* are named.
    """
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"{context} was not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{context} was {type(parsed).__name__}, expected a JSON object")
    return cast("dict[str, object]", parsed)  # pragma: no mutate — runtime no-op


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
        _raise_for_status(response)
        return usage_snapshot_from_response(json.loads(response.body))


def _nonempty_str(value: object) -> str | None:
    """Return *value* as a non-blank string, else None."""
    return value if isinstance(value, str) and value.strip() else None


def _refreshed_tokens(fields: dict[str, object]) -> RefreshedTokens:
    """Build RefreshedTokens from a parsed 2xx grant body, or raise ValueError.

    A malformed success body is schema drift, not a credential to persist
    (ai-usagebar oauth.rs). Field names and types are named in the error;
    values never are.
    """
    access_token = _nonempty_str(fields.get("access_token"))
    if access_token is None:
        raise ValueError("token refresh response field 'access_token' is missing or not a string")
    expires_in = fields.get("expires_in")
    if isinstance(expires_in, bool) or not isinstance(expires_in, (int, float)):
        raise ValueError(
            f"token refresh response field 'expires_in' is {type(expires_in).__name__}, "
            "expected a number"
        )
    return RefreshedTokens(
        access_token=access_token,
        refresh_token=_nonempty_str(fields.get("refresh_token")),
        expires_in_s=float(expires_in),
    )


class AnthropicTokenRefresher(TokenRefresherPort):
    """TokenRefresherPort over ``POST /v1/oauth/token``.

    The RFC 6749 public-client refresh grant, matching claude-swap oauth.py
    ``try_refresh_oauth_credentials`` — two headers, no ``anthropic-beta``.

    Example:
        AnthropicTokenRefresher(UrllibHttpTransport()).refresh(refresh_token)
    """

    def __init__(self, transport: HttpTransportPort) -> None:
        """Inject the HTTP transport (test seam: FakeHttpTransport)."""
        self._transport = transport

    def refresh(self, refresh_token: str) -> RefreshedTokens:
        """Perform the grant and return the rotated tokens.

        Raises AnthropicApiError on non-2xx, HttpTransportError on network
        failure, and ValueError on a malformed 200 body.
        """
        _require_allowed_host(TOKEN_URL)
        headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
        body = json.dumps(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": OAUTH_CLIENT_ID,
            }
        ).encode()
        response = self._transport.request(
            "POST", TOKEN_URL, headers, body, timeout_s=_REFRESH_TIMEOUT_S
        )
        _raise_for_status(response)
        return _refreshed_tokens(_success_object(response.body, "token refresh response"))


class AnthropicIdentityLookup(IdentityLookupPort):
    """IdentityLookupPort over ``GET /api/oauth/profile`` — the identity oracle.

    Matches claude-swap oauth.py ``fetch_oauth_profile``. Fail-open by
    contract: every failure — a non-2xx status, a transport
    error, or a body without a usable ``account.uuid`` — returns ``None``, so
    a switch can proceed pre-fix (claude-swap's exact policy). Three headers,
    no ``anthropic-beta``.

    Example:
        AnthropicIdentityLookup(UrllibHttpTransport()).resolve(access_token)
    """

    def __init__(self, transport: HttpTransportPort) -> None:
        """Inject the HTTP transport (test seam: FakeHttpTransport)."""
        self._transport = transport

    def resolve(self, access_token: str) -> ResolvedIdentity | None:
        """The resolved identity, or None on any failure (never raises)."""
        _require_allowed_host(PROFILE_URL)
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }
        try:
            response = self._transport.request(
                "GET", PROFILE_URL, headers, None, timeout_s=_PROFILE_TIMEOUT_S
            )
        except HttpTransportError:
            return None
        if response.status // 100 != 2:
            return None
        fields = _json_object_or_none(response.body)
        if fields is None:
            return None
        return resolved_identity_from_profile_response(fields)
