"""Cadence policy for the ``/api/oauth/usage`` endpoint — every number in one place.

Evidence: claude-swap ``poll_policy.py`` (read directly, including its git
history and its own measurement notes): the endpoint enforces a ~60-minute
rolling budget of ~28-30 requests per identity for non-first-party User-Agents
(measured 2026-07-11) — not a refilling bucket, so a burst saturates the
identity for up to a full hour. The constants below target a sustained
average of ~1 request/3 minutes (20/hour), leaving headroom for manual
commands and bursts. Constant names are kept identical to claude-swap's for
evidence traceability.

M5 scope (docs/backlog.md): claude-swap's ``threshold``-driven urgent mode
and escalation margin are deferred to M9, whose auto loop is the thing that
actually owns a switch threshold — adding that knob here now, with no
consumer, would be speculative. This module ports the threshold-independent
part: movement-based interval adaptation and jitter (this commit), the
exhausted floor and reset cap, and the post-429 floor/AIMD backoff (both
following in later M5 commits, docs/backlog.md).

Example:
    plan_after_fetch(prev_interval_s=None, prev_pct=None, new_pct=10.0,
                      is_active=True, now_s=1700000000.0)
"""

import random
from collections.abc import Callable
from datetime import datetime

from claude_acc_manager.usage.domain.services.headroom import account_headroom, relevant_windows
from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot

# Freshness floor shared by every caller of the usage cache
# (cache_trust.is_fresh): an entry younger than this is served without any
# fetch, so the maximum sustained rate on one identity is 1/SERVE_TTL_S
# regardless of how many surfaces are open.
SERVE_TTL_S = 180.0

# Normal cadence floor — movement can halve an interval down to this, never
# below.
MIN_INTERVAL_S = 180.0

# Decay ceilings for an account whose usage is not moving: the active
# account stays reasonably fresh, an idle alternate drifts out further.
ACTIVE_MAX_INTERVAL_S = 300.0
CANDIDATE_DEFAULT_INTERVAL_S = 300.0
CANDIDATE_MAX_INTERVAL_S = 600.0

# A binding pct that moved at least this much between polls is being
# consumed somewhere (this machine, another PC, session mode) → tighten; an
# unmoved one backs off toward its ceiling.
MOVEMENT_DELTA_PCT = 1.0

# ±fraction applied to each scheduled interval so independent processes
# drift apart instead of fetching in lockstep.
JITTER_FRAC = 0.1

# Exhaustion is stable enough to poll slowly, but not to stop polling until a
# reported reset — a quota grant or provider-side correction can make an
# account usable again before that timestamp.
EXHAUSTED_INTERVAL_S = 600.0

# Never schedule a poll later than a known window reset (+ slack): stored
# usage is obsolete the moment the window rolls over.
RESET_SLACK_S = 60.0

# While a 429 seen on this token is still "recent" (cache_trust.recent_429),
# floor the planned cadence here so freed capacity accumulates instead of
# being re-spent immediately.
POST_429_MIN_INTERVAL_S = 360.0

# AIMD on a contended budget: the endpoint exposes no remaining-request
# count, only a hard block once already saturated, and the budget is shared
# across every machine polling the same identity with none able to see the
# others. So while 429s recur, each successful poll multiplicatively grows
# the interval (×POST_429_BACKOFF_MULT) toward a wider ceiling — wide enough
# that several machines can each back off far enough to fit under the
# budget together, with no cross-machine coordination. Movement (a real
# success run with no recent 429) decays it back down through the normal
# path above.
POST_429_BACKOFF_MULT = 1.5
POST_429_MAX_INTERVAL_S = 1800.0

# How long a 429 keeps the post-429 floor/AIMD engaged (cache_trust.recent_429):
# the saturation horizon is hour-scale, so a 429 stays "recent" for this long.
RECENT_429_WINDOW_S = 3600.0

# Flat lockout armed on a 429 (M5 plan decision 2: ai-usagebar's model, not
# claude-swap's Retry-After-derived floor — this endpoint's Retry-After is
# documented as unreliable, docs/architecture.md §3). During this window no fetch
# is attempted at all; cache_trust.in_backoff enforces it.
RATE_LIMIT_BACKOFF_S = 300.0

# How long a frozen last_good stays decision-grade after ANY fetch failure
# (cache_trust.trust_ok), capped regardless of a longer reset — trust must
# never be unbounded. claude-swap's general failure ceiling (its
# 429-specific RATE_LIMIT_TRUST_MAX_AGE_S=7200 fallback is folded into this
# one ceiling here, per cache_trust.trust_ok's simplified single-ceiling
# design — M5 has no Retry-After to size a second one).
TRUST_MAX_AGE_S = 3600.0


def binding_pct(snapshot: UsageSnapshot | None, models: tuple[str, ...] = ()) -> float | None:
    """Utilization of the binding (worst) relevant window, or None.

    The complement of :func:`headroom.account_headroom` — the pct
    ``plan_after_fetch`` adapts its cadence on.

    Example:
        binding_pct(snapshot) == 62.0
    """
    headroom = account_headroom(snapshot, models)
    return None if headroom is None else 100.0 - headroom


def parse_reset_epoch(resets_at: str | None) -> float | None:
    """Parse an ISO-8601 ``resets_at`` string to Unix epoch seconds, or None.

    ``datetime.fromisoformat`` accepts a trailing ``Z`` natively on this
    project's Python floor (3.11+) — no manual ``+00:00`` substitution needed.

    Example:
        parse_reset_epoch("2026-05-23T13:30:00Z") == 1779543000.0
    """
    if not resets_at:
        return None
    try:
        return datetime.fromisoformat(resets_at).timestamp()
    except ValueError:
        return None


def limiting_reset_epoch(
    snapshot: UsageSnapshot | None, models: tuple[str, ...] = ()
) -> float | None:
    """Epoch of the latest reset among the ≥100%-utilized relevant windows.

    None when no relevant window is at or over 100% — this is the "when is
    the account usable again" timestamp for an exhausted account.

    Example:
        limiting_reset_epoch(snapshot)
    """
    latest: float | None = None
    for _, pct, resets_at in relevant_windows(snapshot, models):
        if pct < 100.0:
            continue
        reset_epoch = parse_reset_epoch(resets_at)
        if reset_epoch is None:
            continue
        if latest is None:
            latest = reset_epoch
            continue
        # pragma: no mutate justification: at an exact tie the two resets are
        # numerically equal, so keeping the earlier one (">" ) vs overwriting
        # with the later one (">=") returns the same float either way —
        # equivalent by construction, not a killable boundary.
        if reset_epoch > latest:  # pragma: no mutate
            latest = reset_epoch
    return latest


def earliest_future_reset_epoch(
    snapshot: UsageSnapshot | None, now_s: float, models: tuple[str, ...] = ()
) -> float | None:
    """Epoch of the next relevant-window reset ahead of *now_s*, any utilization.

    Example:
        earliest_future_reset_epoch(snapshot, now_s=1700000000.0)
    """
    earliest: float | None = None
    for _, _, resets_at in relevant_windows(snapshot, models):
        reset_epoch = parse_reset_epoch(resets_at)
        if reset_epoch is None or reset_epoch <= now_s:
            continue
        if earliest is None:
            earliest = reset_epoch
            continue
        # pragma: no mutate justification: at an exact tie the two resets are
        # numerically equal, so keeping the earlier one ("<") vs overwriting
        # with the later one ("<=") returns the same float either way —
        # equivalent by construction, not a killable boundary.
        if reset_epoch < earliest:  # pragma: no mutate
            earliest = reset_epoch
    return earliest


def earliest_reset_epoch(
    snapshot: UsageSnapshot | None, models: tuple[str, ...] = ()
) -> float | None:
    """Epoch of the earliest relevant-window reset, past or future.

    Distinct from :func:`earliest_future_reset_epoch` (which the poll-cadence
    cap uses — capping a future poll to a past reset is meaningless): the
    cache-trust check (``cache_trust.trust_ok``) needs the true earliest
    reset, past included, because a window whose own reset has already
    passed is obsolete data — usage_store's rule "once the window resets,
    last_good is obsolete" — not merely "no reset known", which would let
    trust fall back to the age ceiling instead of lapsing.

    Example:
        earliest_reset_epoch(snapshot)
    """
    earliest: float | None = None
    for _, _, resets_at in relevant_windows(snapshot, models):
        reset_epoch = parse_reset_epoch(resets_at)
        if reset_epoch is None:
            continue
        if earliest is None:
            earliest = reset_epoch
            continue
        # pragma: no mutate justification: at an exact tie the two resets are
        # numerically equal, so keeping the earlier one ("<") vs overwriting
        # with the later one ("<=") returns the same float either way —
        # equivalent by construction, not a killable boundary.
        if reset_epoch < earliest:  # pragma: no mutate
            earliest = reset_epoch
    return earliest


def _base_interval(
    prev_interval_s: float | None, prev_pct: float | None, new_pct: float | None, is_active: bool
) -> tuple[float, float]:
    """``(interval, base)`` — the movement-adapted interval and the base it grew from.

    *base* (``prev_interval_s`` or the account-kind default) is exposed
    separately because the post-429 AIMD grows from it too, not from the
    movement-adapted *interval*.
    """
    default = MIN_INTERVAL_S if is_active else CANDIDATE_DEFAULT_INTERVAL_S
    ceiling = ACTIVE_MAX_INTERVAL_S if is_active else CANDIDATE_MAX_INTERVAL_S
    base = prev_interval_s or default
    if prev_pct is None or new_pct is None:
        return default, base
    if abs(new_pct - prev_pct) >= MOVEMENT_DELTA_PCT:
        return max(MIN_INTERVAL_S, base / 2.0), base
    return min(ceiling, max(MIN_INTERVAL_S, base * 1.5)), base


def plan_after_fetch(
    *,
    prev_interval_s: float | None,
    prev_pct: float | None,
    new_pct: float | None,
    is_active: bool,
    headroom: float | None,
    limiting_reset_s: float | None,
    earliest_reset_s: float | None,
    recent_429: bool,
    now_s: float,
    rng: Callable[[], float] = random.random,
) -> tuple[float, float]:
    """``(next_poll_at_s, interval_s)`` for an account just fetched successfully.

    Movement (the binding pct changed ≥ ``MOVEMENT_DELTA_PCT`` since the
    previous poll) halves the interval, floored at ``MIN_INTERVAL_S``. No
    movement backs off ×1.5 toward the account's ceiling (``is_active``
    picks which one). Either pct being unknown uses the default interval for
    the account kind. A recent 429 on this token (``recent_429``) grows the
    interval multiplicatively (AIMD) toward a wider ceiling instead. An
    exhausted account (``headroom <= 0``) floors the interval at
    ``EXHAUSTED_INTERVAL_S`` instead of sleeping until its reset, so an early
    quota grant is still observed promptly. The scheduled time gets
    ``JITTER_FRAC`` noise, then is never later than the relevant future reset
    + ``RESET_SLACK_S`` (``limiting_reset_s`` while exhausted, else
    ``earliest_reset_s``) — a reset in the past or unknown never caps it.

    Example:
        plan_after_fetch(prev_interval_s=300.0, prev_pct=10.0, new_pct=10.0,
                          is_active=False, headroom=90.0, limiting_reset_s=None,
                          earliest_reset_s=None, recent_429=False, now_s=1000.0)
    """
    interval, base = _base_interval(prev_interval_s, prev_pct, new_pct, is_active)
    if recent_429:
        grown = max(base * POST_429_BACKOFF_MULT, POST_429_MIN_INTERVAL_S)
        interval = min(POST_429_MAX_INTERVAL_S, max(interval, grown))
    exhausted = headroom is not None and headroom <= 0.0
    if exhausted:
        interval = max(interval, EXHAUSTED_INTERVAL_S)
    next_poll_at = now_s + interval * (1.0 + JITTER_FRAC * (2.0 * rng() - 1.0))
    reset_s = limiting_reset_s if exhausted else earliest_reset_s
    if reset_s is not None and reset_s > now_s:
        next_poll_at = min(next_poll_at, reset_s + RESET_SLACK_S)
    return next_poll_at, interval
