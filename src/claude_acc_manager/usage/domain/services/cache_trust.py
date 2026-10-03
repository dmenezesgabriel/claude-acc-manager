"""Whether a cached usage measurement is still decision-grade.

A 429 is a polling throttle, not a change in the account's real quota —
usage rises monotonically within a window, so a frozen ``last_good`` is a
valid lower bound right up to the window's own reset (or a fixed ceiling
when no reset is known), never flipped to "unknown" just because time
passed.

Example:
    trust_ok(entry, now_s, earliest_reset_s=None, ceiling_s=3600.0)
"""

from claude_acc_manager.usage.domain.usage_cache_entry import UsageCacheEntry


def is_fresh(entry: UsageCacheEntry, now_s: float, ttl_s: float) -> bool:
    """True when *entry* was fetched less than *ttl_s* ago.

    Never fetched (``fetched_at_s is None``) is never fresh.

    Example:
        is_fresh(entry, now_s=1000.0, ttl_s=180.0)
    """
    return entry.fetched_at_s is not None and now_s - entry.fetched_at_s < ttl_s


def in_backoff(entry: UsageCacheEntry, now_s: float) -> bool:
    """True while *now_s* is still before a set backoff deadline.

    Example:
        in_backoff(entry, now_s=1000.0)
    """
    return entry.backoff_until_s is not None and now_s < entry.backoff_until_s


def recent_429(entry: UsageCacheEntry, now_s: float, window_s: float) -> bool:
    """True while a 429 seen on this token is still within *window_s*.

    Anchored on when the honored backoff *lifts*, not on the 429 itself, so
    an hour-scale block counts its recency from the moment polling resumes
    (otherwise the post-429 cadence floor could never engage on the very
    first post-block success). The anchor only
    moves to ``backoff_until_s`` while that backoff was actually caused by
    the 429 (``last_error == "http-429"``) — a later, unrelated failure must
    not re-arm recency past the original stamp.

    Example:
        recent_429(entry, now_s=1000.0, window_s=3600.0)
    """
    if entry.last_429_at_s is None:
        return False
    anchor = entry.last_429_at_s
    if entry.last_error == "http-429" and entry.backoff_until_s is not None:
        # pragma: no mutate justification: at exact equality the reassignment
        # below sets anchor to the same value it already holds, so `>` vs
        # `>=` here is unobservable in the returned boolean — equivalent by
        # construction, not a killable boundary.
        if entry.backoff_until_s > anchor:  # pragma: no mutate
            anchor = entry.backoff_until_s
    return now_s < anchor + window_s


def trust_ok(
    entry: UsageCacheEntry, now_s: float, earliest_reset_s: float | None, ceiling_s: float
) -> bool:
    """True when a stale ``last_good`` is still safe to serve as a decision.

    Trusted while its age is under *ceiling_s* AND (no reset is known yet,
    or the earliest relevant window hasn't reset). No ``last_good`` at all
    is never trusted.

    Example:
        trust_ok(entry, now_s=1000.0, earliest_reset_s=None, ceiling_s=3600.0)
    """
    if entry.last_good is None or entry.fetched_at_s is None:
        return False
    if now_s - entry.fetched_at_s >= ceiling_s:
        return False
    return earliest_reset_s is None or now_s < earliest_reset_s
