"""Whether a stored OAuth access token is due for refresh.

Evidence: claude-swap ``oauth.py`` ``is_oauth_token_expired``
(``OAUTH_EXPIRY_BUFFER_MS = 5 * 60 * 1000``): a token is treated as expired
once it is within 5 minutes of its ``expiresAt`` (or already past it), so a
refresh started now has time to land before the old token actually stops
working. Epoch milliseconds throughout, matching the credential file's own
``expiresAt`` unit (plan §2.1). A missing/unmeasurable expiry is schema
drift, not evidence of staleness — treated as not-expired, same as
claude-swap's non-numeric guard.

Example:
    token_expired(credential.expires_at_ms, clock.now_epoch_s() * 1000)
"""

DEFAULT_SKEW_MS = 5 * 60 * 1000.0


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
