"""Ports of the usage component — the single map of every boundary."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from claude_acc_manager.usage.domain.resolved_identity import ResolvedIdentity
from claude_acc_manager.usage.domain.usage_cache_entry import UsageCacheEntry
from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot


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


class AnthropicApiError(Exception):
    """A non-2xx response from an Anthropic OAuth endpoint.

    Carries only the HTTP status and the RFC 6749 top-level ``error`` code
    (e.g. ``"invalid_grant"``) — never the raw response body, so a token an
    error body happens to echo can never reach a log or a traceback (plan
    §5.4 redaction guarantee). ``error_code`` is ``None`` when the body
    carried no such field or was not JSON.

    Example:
        raise AnthropicApiError(status=400, error_code="invalid_grant")
    """

    def __init__(self, status: int, error_code: str | None) -> None:
        """Record *status* and the classified *error_code* (never the body)."""
        self.status = status
        self.error_code = error_code
        super().__init__(f"Anthropic API returned {status} (error={error_code!r})")


@runtime_checkable
class UsageApiPort(Protocol):
    """Boundary for fetching one account's usage snapshot.

    Example:
        snapshot = usage_api.fetch_usage(access_token)
    """

    def fetch_usage(self, access_token: str) -> UsageSnapshot:
        """Raises AnthropicApiError on non-2xx, HttpTransportError on network failure."""
        ...


@dataclass(frozen=True)
class RefreshedTokens:
    """The result of a successful refresh-token grant.

    ``refresh_token`` is ``None`` when the server did not rotate it — the
    caller keeps the one it already holds (claude-swap oauth.py:191).
    ``expires_in_s`` is the raw relative lifetime from the response; turning
    it into an absolute expiry needs a clock and belongs to the caller
    (the M5 fetch use case), not this transport-thin client.

    Example:
        RefreshedTokens(access_token="new-at", refresh_token="new-rt", expires_in_s=3600.0)
    """

    access_token: str
    refresh_token: str | None
    expires_in_s: float


@runtime_checkable
class TokenRefresherPort(Protocol):
    """Boundary for rotating an OAuth access token via the RFC 6749 refresh grant.

    Example:
        rotated = refresher.refresh(refresh_token)
    """

    def refresh(self, refresh_token: str) -> RefreshedTokens:
        """Perform the grant and return the rotated tokens.

        Raises AnthropicApiError on non-2xx (the caller classifies
        ``invalid_grant``), HttpTransportError on network failure, and
        ValueError on a malformed 200 body.
        """
        ...


@runtime_checkable
class IdentityLookupPort(Protocol):
    """Boundary for resolving a credential's owning account (the identity oracle).

    Strictly advisory — matches claude-swap ``fetch_oauth_profile``: callers
    treat ``None`` as "unresolvable", never as an error, so a switch proceeds
    pre-fix on ``None`` rather than failing. This is the one port here that
    never raises for a network or HTTP error.

    Example:
        identity = identity_lookup.resolve(access_token)
    """

    def resolve(self, access_token: str) -> ResolvedIdentity | None:
        """None on any failure: non-2xx, network failure, or malformed body."""
        ...


@runtime_checkable
class ClockPort(Protocol):
    """Boundary for wall-clock reads driving poll-cadence arithmetic.

    Usage-local: ``accounts`` has its own same-named port shaped
    ``now_iso() -> str`` for display timestamps, but ``usage`` cannot import
    it (import-linter: "usage never imports accounts") and needs epoch
    seconds for cache-freshness and cadence math, not a display string.

    Example:
        elapsed_s = clock.now_epoch_s() - entry.fetched_at_s
    """

    def now_epoch_s(self) -> float:
        """Current time as Unix epoch seconds."""
        ...


@runtime_checkable
class UsageCachePort(Protocol):
    """Persistence boundary for one account's cached usage measurement.

    Keyed by account name string, matching ``AccountStorePort`` — ``usage``
    cannot import the ``accounts.domain.value_objects.AccountName`` value
    object (import-linter: "usage never imports accounts"), so the key is a
    plain string here; callers convert.

    Example:
        entry = cache.load("work")
        cache.save("work", replace(entry, last_good=snapshot))
    """

    def load(self, account_key: str) -> UsageCacheEntry:
        """The account's cached entry, or EMPTY_USAGE_CACHE_ENTRY when unknown."""
        ...

    def save(self, account_key: str, entry: UsageCacheEntry) -> None:
        """Replace the account's cached entry."""
        ...
