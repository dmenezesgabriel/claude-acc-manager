"""Cadence policy for the ``/api/oauth/usage`` endpoint — every number in one place.

Evidence: claude-swap ``poll_policy.py`` (read directly, including its git
history and its own measurement notes): the endpoint enforces a ~60-minute
rolling budget of ~28-30 requests per identity for non-first-party User-Agents
(measured 2026-07-11) — not a refilling bucket, so a burst saturates the
identity for up to a full hour. The constants below target a sustained
average of ~1 request/3 minutes (20/hour), leaving headroom for manual
commands and bursts. Constant names are kept identical to claude-swap's for
evidence traceability.

M5 scope (plan §9 decision 1): claude-swap's ``threshold``-driven urgent mode
and escalation margin are deferred to M9, whose auto loop is the thing that
actually owns a switch threshold — adding that knob here now, with no
consumer, would be speculative. This module ports the threshold-independent
part: movement-based interval adaptation and jitter (this commit), the
exhausted floor and reset cap, and the post-429 floor/AIMD backoff (both
following in later M5 commits, plan §9).

Example:
    plan_after_fetch(prev_interval_s=None, prev_pct=None, new_pct=10.0,
                      is_active=True, now_s=1700000000.0)
"""

import random
from collections.abc import Callable

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


def _base_interval(
    prev_interval_s: float | None, prev_pct: float | None, new_pct: float | None, is_active: bool
) -> float:
    """Movement-adapted interval, before the exhausted floor or post-429 backoff."""
    default = MIN_INTERVAL_S if is_active else CANDIDATE_DEFAULT_INTERVAL_S
    ceiling = ACTIVE_MAX_INTERVAL_S if is_active else CANDIDATE_MAX_INTERVAL_S
    base = prev_interval_s or default
    if prev_pct is None or new_pct is None:
        return default
    if abs(new_pct - prev_pct) >= MOVEMENT_DELTA_PCT:
        return max(MIN_INTERVAL_S, base / 2.0)
    return min(ceiling, max(MIN_INTERVAL_S, base * 1.5))


def plan_after_fetch(
    *,
    prev_interval_s: float | None,
    prev_pct: float | None,
    new_pct: float | None,
    is_active: bool,
    headroom: float | None,
    limiting_reset_s: float | None,
    earliest_reset_s: float | None,
    now_s: float,
    rng: Callable[[], float] = random.random,
) -> tuple[float, float]:
    """``(next_poll_at_s, interval_s)`` for an account just fetched successfully.

    Movement (the binding pct changed ≥ ``MOVEMENT_DELTA_PCT`` since the
    previous poll) halves the interval, floored at ``MIN_INTERVAL_S``. No
    movement backs off ×1.5 toward the account's ceiling (``is_active``
    picks which one). Either pct being unknown uses the default interval for
    the account kind. An exhausted account (``headroom <= 0``) floors the
    interval at ``EXHAUSTED_INTERVAL_S`` instead of sleeping until its reset,
    so an early quota grant is still observed promptly. The scheduled time
    gets ``JITTER_FRAC`` noise, then is never later than the relevant future
    reset + ``RESET_SLACK_S`` (``limiting_reset_s`` while exhausted, else
    ``earliest_reset_s``) — a reset in the past or unknown never caps it.

    Example:
        plan_after_fetch(prev_interval_s=300.0, prev_pct=10.0, new_pct=10.0,
                          is_active=False, headroom=90.0, limiting_reset_s=None,
                          earliest_reset_s=None, now_s=1000.0)
    """
    interval = _base_interval(prev_interval_s, prev_pct, new_pct, is_active)
    exhausted = headroom is not None and headroom <= 0.0
    if exhausted:
        interval = max(interval, EXHAUSTED_INTERVAL_S)
    next_poll_at = now_s + interval * (1.0 + JITTER_FRAC * (2.0 * rng() - 1.0))
    reset_s = limiting_reset_s if exhausted else earliest_reset_s
    if reset_s is not None and reset_s > now_s:
        next_poll_at = min(next_poll_at, reset_s + RESET_SLACK_S)
    return next_poll_at, interval
