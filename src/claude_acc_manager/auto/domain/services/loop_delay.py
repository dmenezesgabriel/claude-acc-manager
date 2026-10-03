"""loop_delay — how long the auto loop sleeps between ticks.

Pure policy over the engine's loop-facing hints (``sleep_until_s``,
``blocked_long_wait``, and the active row's next-poll deadline): no ports,
no clock — the engine reads its own fields after every ``tick()`` and
passes everything in.

Normal cadence is the configured interval with ±10% jitter so several
machines do not synchronize their API hits. BLOCKED outcomes re-route: a
known recovery target sleeps toward it (floored at one interval, capped at
``MAX_SLEEP_S`` — quota can land before the reported reset, so oversleeping
would suppress the fetch that discovers it), a long wait with no provable
recovery sleeps ``NO_RESET_FALLBACK_S``, and a block that can resolve on
any tick (hysteresis, unreadable usage) keeps the normal jittered cadence.

Example:
    delay = next_delay(outcome, interval_s=60.0, now_s=now,
                       sleep_until_s=None, blocked_long_wait=False,
                       next_poll_due_s=None, jitter=random.random())
"""

from claude_acc_manager.auto.domain.auto_event import TickOutcome
from claude_acc_manager.usage.domain.services.poll_policy import (
    EXHAUSTED_INTERVAL_S,
    JITTER_FRAC,
    URGENT_INTERVAL_S,
)

# Recheck at the exhausted-poll cadence even when a reset is far out.
MAX_SLEEP_S = EXHAUSTED_INTERVAL_S
# No provable recovery anywhere: hold a 5-minute cadence — nothing can
# improve sooner, so a tighter loop would only burn fetch budget.
NO_RESET_FALLBACK_S = 300.0


def next_delay(
    outcome: TickOutcome,
    *,
    interval_s: float,
    now_s: float,
    sleep_until_s: float | None,
    blocked_long_wait: bool,
    next_poll_due_s: float | None,
    jitter: float,
) -> float:
    """Seconds until the next tick.

    *jitter* is the caller's ``random.random()`` draw in [0, 1) — passing
    it in keeps the policy pure and the boundaries testable.
    """
    if outcome is TickOutcome.BLOCKED:
        if sleep_until_s is not None:
            return min(max(sleep_until_s - now_s, interval_s), MAX_SLEEP_S)
        if blocked_long_wait:
            return max(interval_s, NO_RESET_FALLBACK_S)
    delay_s = interval_s * (1.0 - JITTER_FRAC + 2.0 * JITTER_FRAC * jitter)
    return respect_poll_plan(delay_s, next_poll_due_s=next_poll_due_s, now_s=now_s)


def respect_poll_plan(delay_s: float, *, next_poll_due_s: float | None, now_s: float) -> float:
    """Shorten a normal-cadence sleep to the store's own next-poll time.

    Only ever shortens — the 429 budget lives in the plan — and never
    below ``URGENT_INTERVAL_S``, the planner's own floor. ``None`` means
    the deadline is unknown and the delay stands.
    """
    if next_poll_due_s is None:
        return delay_s
    due_in = next_poll_due_s - now_s
    return min(delay_s, max(due_in, URGENT_INTERVAL_S))
