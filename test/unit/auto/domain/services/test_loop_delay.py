"""loop_delay — jitter bounds, blocked sleeps, the plan-respecting floor."""

import pytest

from claude_acc_manager.auto.domain.auto_event import TickOutcome
from claude_acc_manager.auto.domain.services.loop_delay import (
    MAX_SLEEP_S,
    next_delay,
    respect_poll_plan,
)
from claude_acc_manager.usage.domain.services.poll_policy import URGENT_INTERVAL_S

NOW_S = 1_000_000.0


def _delay(
    outcome: TickOutcome,
    *,
    interval_s: float = 100.0,
    sleep_until_s: float | None = None,
    blocked_long_wait: bool = False,
    next_poll_due_s: float | None = None,
    jitter: float = 0.5,
) -> float:
    return next_delay(
        outcome,
        interval_s=interval_s,
        now_s=NOW_S,
        sleep_until_s=sleep_until_s,
        blocked_long_wait=blocked_long_wait,
        next_poll_due_s=next_poll_due_s,
        jitter=jitter,
    )


class TestNormalCadence:
    def test_jitter_endpoints_bracket_the_interval(self) -> None:
        # ±10%: 0 → 0.9×, 1 → 1.1×
        assert _delay(TickOutcome.NO_ACTION, jitter=0.0) == pytest.approx(90.0)
        assert _delay(TickOutcome.NO_ACTION, jitter=1.0) == pytest.approx(110.0)

    def test_mid_jitter_hits_the_interval(self) -> None:
        assert _delay(TickOutcome.NO_ACTION, jitter=0.5) == pytest.approx(100.0)

    def test_a_sooner_deadline_shortens_the_sleep(self) -> None:
        assert _delay(TickOutcome.NO_ACTION, next_poll_due_s=NOW_S + 75.0) == 75.0

    def test_a_deadline_under_the_floor_still_waits_for_it(self) -> None:
        # 50s out is under URGENT_INTERVAL_S — the planner's floor wins
        assert _delay(TickOutcome.NO_ACTION, next_poll_due_s=NOW_S + 50.0) == 60.0

    def test_a_farther_deadline_leaves_the_delay(self) -> None:
        assert _delay(TickOutcome.NO_ACTION, next_poll_due_s=NOW_S + 500.0) == 100.0

    def test_an_overdue_deadline_floors_at_urgent(self) -> None:
        # the row is late — shorten to the planner's floor, not to zero
        assert _delay(TickOutcome.NO_ACTION, next_poll_due_s=NOW_S - 30.0) == 60.0

    def test_a_sub_floor_delay_is_never_raised(self) -> None:
        # shorten-only: a 45s jittered delay stays 45s even overdue
        assert (
            _delay(
                TickOutcome.NO_ACTION,
                interval_s=50.0,
                jitter=0.0,
                next_poll_due_s=NOW_S - 30.0,
            )
            == 45.0
        )


class TestBlockedOutcomes:
    def test_a_known_recovery_sleeps_until_it(self) -> None:
        assert _delay(TickOutcome.BLOCKED, interval_s=60.0, sleep_until_s=NOW_S + 400.0) == 400.0

    def test_a_far_recovery_is_capped(self) -> None:
        assert (
            _delay(TickOutcome.BLOCKED, interval_s=60.0, sleep_until_s=NOW_S + 5000.0)
            == MAX_SLEEP_S
        )

    def test_a_near_recovery_still_waits_one_interval(self) -> None:
        # the floor keeps the next tick from hot-looping on a stale reset
        assert _delay(TickOutcome.BLOCKED, interval_s=60.0, sleep_until_s=NOW_S + 30.0) == 60.0

    def test_no_provable_recovery_holds_the_fallback(self) -> None:
        assert _delay(TickOutcome.BLOCKED, interval_s=60.0, blocked_long_wait=True) == 300.0
        assert _delay(TickOutcome.BLOCKED, interval_s=400.0, blocked_long_wait=True) == 400.0

    def test_a_short_block_keeps_the_cadence(self) -> None:
        # hysteresis / unreadable-usage blocks can resolve any tick
        assert _delay(TickOutcome.BLOCKED, interval_s=60.0, jitter=0.5) == 60.0

    def test_non_blocked_outcomes_ignore_the_sleep_hints(self) -> None:
        for outcome in (TickOutcome.SWITCHED, TickOutcome.NO_ACTION, TickOutcome.ERROR):
            assert (
                _delay(
                    outcome,
                    interval_s=60.0,
                    sleep_until_s=NOW_S + 99999.0,
                    blocked_long_wait=True,
                    jitter=0.5,
                )
                == 60.0
            )


class TestRespectPollPlan:
    def test_no_deadline_returns_the_delay(self) -> None:
        assert respect_poll_plan(90.0, next_poll_due_s=None, now_s=NOW_S) == 90.0

    def test_a_due_deadline_exactly_at_the_floor(self) -> None:
        assert (
            respect_poll_plan(90.0, next_poll_due_s=NOW_S + URGENT_INTERVAL_S, now_s=NOW_S)
            == URGENT_INTERVAL_S
        )

    def test_a_deadline_inside_the_delay_wins(self) -> None:
        assert respect_poll_plan(90.0, next_poll_due_s=NOW_S + 75.0, now_s=NOW_S) == 75.0
