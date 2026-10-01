"""A stored OAuth credential's usable fields, and whether it's due for refresh.

Evidence: claude-swap ``oauth.py`` ``is_oauth_token_expired``
(``OAUTH_EXPIRY_BUFFER_MS = 5 * 60 * 1000``): a token is treated as expired
once it is within 5 minutes of its ``expiresAt`` (or already past it), so a
refresh started now has time to land before the old token actually stops
working. Epoch milliseconds throughout, matching the credential file's own
``expiresAt`` unit (docs/architecture.md §3). A missing/unmeasurable expiry is schema
drift, not evidence of staleness — treated as not-expired, same as
claude-swap's non-numeric guard.

``StoredOAuthCredential`` is the minimal projection of the
``claudeAiOauth`` block ``FetchAccountUsage`` needs — not the whole blob (it
also carries ``scopes``, ``subscriptionType``, ``rateLimitTier``, an
optional sibling ``organizationUuid``, none of which the fetch use case
reads). ``accounts`` may import ``usage`` (ADR-0010), so the
``AccountCredentialStore`` adapter that reads the real file lives in
``accounts/infrastructure`` and calls the parser below — this module never
touches a filesystem.

Example:
    token_expired(credential.expires_at_ms, clock.now_epoch_s() * 1000)
"""

from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_SKEW_MS = 5 * 60 * 1000.0


@dataclass(frozen=True)
class StoredOAuthCredential:
    """The three ``claudeAiOauth`` fields a usage fetch needs.

    Example:
        StoredOAuthCredential(access_token="at-1", refresh_token="rt-1", expires_at_ms=123.0)
    """

    access_token: str
    refresh_token: str | None
    expires_at_ms: float | None


def _nonempty_str(value: object) -> str | None:
    """Return *value* as a non-blank string, else None."""
    return value if isinstance(value, str) and value else None


def _numeric(value: object) -> float | None:
    """Return *value* as a float, or None — bool is an int subclass, excluded."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def stored_credential_from_claude_ai_oauth(
    data: Mapping[str, object],
) -> StoredOAuthCredential | None:
    """Parse a loaded ``claudeAiOauth`` block.

    ``None`` when there is no usable ``accessToken`` — a missing/blank
    access token means no usable credential, not a parse failure (schema
    drift is the caller's file-tear concern, not this parser's). A missing
    or blank ``refreshToken`` and a missing/non-numeric ``expiresAt`` are
    each independently optional, matching this codebase's other wire
    parsers (``usage_snapshot.py``, ``resolved_identity.py``).

    Example:
        stored_credential_from_claude_ai_oauth({"accessToken": "at-1"})
    """
    access_token = _nonempty_str(data.get("accessToken"))
    if access_token is None:
        return None
    return StoredOAuthCredential(
        access_token=access_token,
        refresh_token=_nonempty_str(data.get("refreshToken")),
        expires_at_ms=_numeric(data.get("expiresAt")),
    )


def token_expired(
    expires_at_ms: float | None, now_ms: float, skew_ms: float = DEFAULT_SKEW_MS
) -> bool:
    """True once *expires_at_ms* is within *skew_ms* of *now_ms*, or past it.

    ``None`` (no expiry known) is never expired.

    Example:
        token_expired(1_000_300_000.0, 1_000_000_000.0)  # True (5-min skew)
    """
    if expires_at_ms is None:
        return False
    return now_ms + skew_ms >= expires_at_ms
