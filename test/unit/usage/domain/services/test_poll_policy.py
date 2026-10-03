"""Unit tests for usage.domain.services.poll_policy.

The plan_after_fetch contract over our signature, which takes an
already-extracted binding pct (from headroom.account_headroom) rather than
a raw usage dict. The threshold/urgent-mode band and the
due-candidate/overslept-plan helpers serve the auto loop's scheduler.
"""

import itertools
from dataclasses import replace

import pytest

from claude_acc_manager.usage.domain.services import poll_policy
from claude_acc_manager.usage.domain.usage_cache_entry import (
    EMPTY_USAGE_CACHE_ENTRY,
    UsageCacheEntry,
)
from claude_acc_manager.usage.domain.usage_snapshot import ScopedWindow, UsageSnapshot, UsageWindow

NOW = 1_000_000.0
HALF = lambda: 0.5  # noqa: E731 — rng midpoint: jitter factor exactly 1.0


def _plan(**overrides: object) -> tuple[float, float]:
    kwargs: dict[str, object] = {
        "prev_interval_s": None,
        "prev_pct": None,
        "new_pct": 10.0,
        "is_active": False,
        "headroom": None,
        "limiting_reset_s": None,
        "earliest_reset_s": None,
        "recent_429": False,
        "threshold": 90.0,
        "now_s": NOW,
        "rng": HALF,
    }
    kwargs.update(overrides)
    return poll_policy.plan_after_fetch(**kwargs)  # type: ignore[arg-type]


class TestIntervalAdaptation:
    def test_first_fetch_uses_defaults(self):
        _, active = _plan(is_active=True)
        _, candidate = _plan(is_active=False)
        assert active == poll_policy.MIN_INTERVAL_S
        assert candidate == poll_policy.CANDIDATE_DEFAULT_INTERVAL_S

    def test_unmoved_decays_toward_the_ceiling(self):
        _, interval = _plan(prev_interval_s=300.0, prev_pct=10.0)
        assert interval == 450.0

    def test_unmoved_decay_caps_at_the_candidate_ceiling(self):
        _, capped = _plan(prev_interval_s=500.0, prev_pct=10.0)
        assert capped == poll_policy.CANDIDATE_MAX_INTERVAL_S

    def test_unmoved_decay_caps_at_the_active_ceiling(self):
        _, active_capped = _plan(prev_interval_s=250.0, prev_pct=10.0, is_active=True)
        assert active_capped == poll_policy.ACTIVE_MAX_INTERVAL_S

    def test_movement_halves_floored_at_min(self):
        _, interval = _plan(prev_interval_s=600.0, prev_pct=10.0, new_pct=15.0)
        assert interval == 300.0

    def test_movement_halving_never_drops_below_the_floor(self):
        _, floored = _plan(prev_interval_s=200.0, prev_pct=10.0, new_pct=15.0)
        assert floored == poll_policy.MIN_INTERVAL_S

    def test_sub_delta_wiggle_is_not_movement(self):
        _, interval = _plan(prev_interval_s=300.0, prev_pct=10.0, new_pct=10.5)
        assert interval == 450.0

    def test_delta_exactly_at_the_threshold_is_movement(self):
        _, interval = _plan(
            prev_interval_s=600.0, prev_pct=10.0, new_pct=10.0 + poll_policy.MOVEMENT_DELTA_PCT
        )
        assert interval == 300.0

    def test_unknown_new_pct_uses_the_default(self):
        _, interval = _plan(prev_interval_s=600.0, prev_pct=10.0, new_pct=None)
        assert interval == poll_policy.CANDIDATE_DEFAULT_INTERVAL_S

    def test_unknown_prev_pct_uses_the_default(self):
        _, interval = _plan(prev_interval_s=600.0, prev_pct=None, new_pct=10.0)
        assert interval == poll_policy.CANDIDATE_DEFAULT_INTERVAL_S


class TestExhaustedFloor:
    def test_at_limit_floors_the_interval(self):
        _, interval = _plan(headroom=0.0)
        assert interval == poll_policy.EXHAUSTED_INTERVAL_S

    def test_negative_headroom_also_floors_the_interval(self):
        _, interval = _plan(headroom=-5.0)
        assert interval == poll_policy.EXHAUSTED_INTERVAL_S

    def test_positive_headroom_does_not_floor_the_interval(self):
        _, interval = _plan(headroom=0.1)
        assert interval != poll_policy.EXHAUSTED_INTERVAL_S


class TestResetCapping:
    def test_poll_never_scheduled_past_a_future_reset(self):
        reset_s = NOW + 90.0
        next_poll, interval = _plan(headroom=60.0, earliest_reset_s=reset_s)
        assert next_poll == pytest.approx(reset_s + poll_policy.RESET_SLACK_S)
        assert interval == poll_policy.CANDIDATE_DEFAULT_INTERVAL_S

    def test_at_limit_keeps_bounded_polling_before_a_distant_reset(self):
        reset_s = NOW + 7_200.0
        next_poll, interval = _plan(headroom=0.0, limiting_reset_s=reset_s)
        assert interval == poll_policy.EXHAUSTED_INTERVAL_S
        assert next_poll == pytest.approx(NOW + interval)
        assert next_poll < reset_s

    def test_at_limit_poll_is_pulled_to_an_imminent_reset(self):
        reset_s = NOW + 90.0
        next_poll, interval = _plan(headroom=0.0, limiting_reset_s=reset_s)
        assert interval == poll_policy.EXHAUSTED_INTERVAL_S
        assert next_poll == pytest.approx(reset_s + poll_policy.RESET_SLACK_S)

    @pytest.mark.parametrize("reset_s", [NOW - 90.0, NOW])
    def test_at_limit_ignores_a_non_future_reset(self, reset_s):
        next_poll, interval = _plan(headroom=0.0, limiting_reset_s=reset_s)
        assert interval == poll_policy.EXHAUSTED_INTERVAL_S
        assert next_poll == pytest.approx(NOW + interval)

    def test_active_at_limit_uses_the_same_bounded_recovery_probe(self):
        reset_s = NOW + 7_200.0
        next_poll, interval = _plan(headroom=0.0, limiting_reset_s=reset_s, is_active=True)
        assert interval == poll_policy.EXHAUSTED_INTERVAL_S
        assert next_poll == pytest.approx(NOW + interval)


class TestJitter:
    def test_jitter_bounds(self):
        interval = poll_policy.CANDIDATE_DEFAULT_INTERVAL_S
        early, _ = _plan(rng=lambda: 0.0)
        late, _ = _plan(rng=lambda: 1.0)
        assert early == NOW + interval * (1.0 - poll_policy.JITTER_FRAC)
        assert late == NOW + interval * (1.0 + poll_policy.JITTER_FRAC)


class TestPost429Floor:
    def test_recent_429_floors_the_cadence(self):
        _, interval = _plan(recent_429=True, prev_pct=10.0)
        assert interval >= poll_policy.POST_429_MIN_INTERVAL_S

    def test_a_slower_learned_cadence_survives_the_floor(self):
        # A learned interval already above the floor is grown (x1.5), never
        # dropped back down to the floor.
        _, interval = _plan(recent_429=True, prev_interval_s=590.0, prev_pct=10.0)
        assert interval == pytest.approx(590.0 * poll_policy.POST_429_BACKOFF_MULT)
        assert interval > poll_policy.POST_429_MIN_INTERVAL_S


class TestPost429Aimd:
    """AIMD backoff on a contended token: while 429s recur, each successful
    poll multiplicatively increases the interval toward a wider 429 ceiling,
    so independent machines sharing one token each retreat and their
    combined poll rate converges under the endpoint budget."""

    def test_recent_429_multiplicatively_increases_from_the_floor(self):
        _, interval = _plan(
            recent_429=True, prev_interval_s=poll_policy.POST_429_MIN_INTERVAL_S, prev_pct=10.0
        )
        assert interval == pytest.approx(
            poll_policy.POST_429_MIN_INTERVAL_S * poll_policy.POST_429_BACKOFF_MULT
        )

    def test_recent_429_ceiling_exceeds_the_normal_candidate_max(self):
        assert poll_policy.POST_429_MAX_INTERVAL_S > poll_policy.CANDIDATE_MAX_INTERVAL_S
        _, interval = _plan(
            recent_429=True, prev_interval_s=poll_policy.POST_429_MAX_INTERVAL_S, prev_pct=10.0
        )
        assert interval == poll_policy.POST_429_MAX_INTERVAL_S

    def test_no_429_uses_the_normal_ceiling(self):
        _, interval = _plan(recent_429=False, prev_interval_s=590.0, prev_pct=10.0)
        assert interval == poll_policy.CANDIDATE_MAX_INTERVAL_S

    def _converge_trajectory(self, recent_429: bool, rounds: int = 12) -> list[float]:
        # Worst case for convergence: an unmoving account that keeps 429ing
        # (movement decay would only shorten the interval).
        prev = None
        trajectory = []
        for _ in range(rounds):
            _, interval = _plan(
                recent_429=recent_429, prev_interval_s=prev, prev_pct=10.0, new_pct=10.0
            )
            trajectory.append(interval)
            prev = interval
        return trajectory

    def test_sustained_429_grows_the_interval_to_the_wide_ceiling(self):
        trajectory = self._converge_trajectory(recent_429=True)
        assert trajectory[-1] == poll_policy.POST_429_MAX_INTERVAL_S
        assert trajectory == sorted(trajectory)
        for a, b in itertools.pairwise(trajectory):
            if b < poll_policy.POST_429_MAX_INTERVAL_S:
                assert b == pytest.approx(a * poll_policy.POST_429_BACKOFF_MULT)

    def test_without_recency_the_interval_is_capped_at_the_narrow_ceiling(self):
        # The deadlock the AIMD exists to break: without the recency signal,
        # N machines sharing a token would each jam at the narrow ceiling and
        # their combined rate could sit above the budget forever.
        trajectory = self._converge_trajectory(recent_429=False)
        assert max(trajectory) == poll_policy.CANDIDATE_MAX_INTERVAL_S


class TestBudgetInvariants:
    """Relationships the measured rate limit demands of the constants.

    Measured 2026-07-11: a rolling ~60-minute window of ~28-30 requests per
    identity for non-first-party User-Agents — not a refilling bucket, so a
    saturated window needs up to 60 minutes to recover (the poll_policy
    module docstring records the budget).
    """

    def test_sustained_floor_stays_under_the_hourly_cap(self):
        # 3600/180 = 20 requests/hour vs the measured ~28-30/hour window.
        assert poll_policy.MIN_INTERVAL_S >= 180.0
        assert poll_policy.SERVE_TTL_S >= 180.0

    def test_post_429_floor_covers_the_saturation_horizon(self):
        # A 429 means the trailing hour's budget is spent; it takes up to 60
        # minutes for that burst to age out entirely.
        assert poll_policy.RECENT_429_WINDOW_S >= 3600.0
        assert poll_policy.POST_429_MIN_INTERVAL_S >= poll_policy.MIN_INTERVAL_S


def _snapshot(
    five_hour: float | None = None,
    seven_day: float | None = None,
    scoped: tuple[ScopedWindow, ...] = (),
) -> UsageSnapshot:
    return UsageSnapshot(
        five_hour=None if five_hour is None else UsageWindow(pct=five_hour, resets_at=None),
        seven_day=None if seven_day is None else UsageWindow(pct=seven_day, resets_at=None),
        scoped=scoped,
    )


class TestBindingPct:
    """binding_pct = 100 - account_headroom: the pct plan_after_fetch adapts on."""

    def test_is_the_max_relevant_utilization(self):
        assert poll_policy.binding_pct(_snapshot(five_hour=20.0, seven_day=80.0)) == 80.0

    def test_unknown_when_no_window_data(self):
        assert poll_policy.binding_pct(_snapshot()) is None

    def test_none_snapshot_is_unknown(self):
        assert poll_policy.binding_pct(None) is None

    def test_models_are_forwarded_to_account_headroom(self):
        # a named model-scoped window only binds when models names it — pins
        # that binding_pct passes `models` through rather than dropping it
        snapshot = _snapshot(five_hour=10.0, scoped=(ScopedWindow("Fable", 95.0, None),))
        assert poll_policy.binding_pct(snapshot) == 10.0
        assert poll_policy.binding_pct(snapshot, models=("Fable",)) == 95.0


class TestParseResetEpoch:
    def test_parses_a_z_suffixed_timestamp(self):
        assert poll_policy.parse_reset_epoch("2026-05-23T13:30:00Z") == pytest.approx(
            1_779_543_000.0
        )

    def test_none_is_none(self):
        assert poll_policy.parse_reset_epoch(None) is None

    def test_blank_is_none(self):
        assert poll_policy.parse_reset_epoch("") is None

    def test_unparseable_is_none(self):
        assert poll_policy.parse_reset_epoch("not-a-timestamp") is None


class TestLimitingResetEpoch:
    """Epoch of the latest reset among the >=100% relevant windows."""

    def test_picks_the_latest_of_the_maxed_windows(self):
        snapshot = UsageSnapshot(
            five_hour=UsageWindow(100.0, "2026-05-20T00:00:00Z"),
            seven_day=UsageWindow(100.0, "2026-05-25T00:00:00Z"),
            scoped=(),
        )
        assert poll_policy.limiting_reset_epoch(snapshot) == poll_policy.parse_reset_epoch(
            "2026-05-25T00:00:00Z"
        )

    def test_ignores_a_window_below_100(self):
        snapshot = _snapshot(five_hour=99.9, seven_day=None)
        assert poll_policy.limiting_reset_epoch(snapshot) is None

    def test_a_below_100_window_is_skipped_not_a_stop(self):
        # pins `continue`, not `break`: an earlier below-100 window must not
        # hide a later maxed one
        snapshot = UsageSnapshot(
            five_hour=UsageWindow(50.0, "2026-05-20T00:00:00Z"),
            seven_day=UsageWindow(100.0, "2026-05-25T00:00:00Z"),
            scoped=(),
        )
        assert poll_policy.limiting_reset_epoch(snapshot) == poll_policy.parse_reset_epoch(
            "2026-05-25T00:00:00Z"
        )

    def test_an_unparseable_reset_on_a_later_maxed_window_does_not_displace_the_latest(self):
        snapshot = UsageSnapshot(
            five_hour=UsageWindow(100.0, "2026-05-20T00:00:00Z"),
            seven_day=UsageWindow(100.0, "not-a-timestamp"),
            scoped=(),
        )
        assert poll_policy.limiting_reset_epoch(snapshot) == poll_policy.parse_reset_epoch(
            "2026-05-20T00:00:00Z"
        )

    def test_models_are_forwarded(self):
        snapshot = _snapshot(scoped=(ScopedWindow("Fable", 100.0, "2026-05-25T00:00:00Z"),))
        assert poll_policy.limiting_reset_epoch(snapshot) is None
        assert poll_policy.limiting_reset_epoch(
            snapshot, models=("Fable",)
        ) == poll_policy.parse_reset_epoch("2026-05-25T00:00:00Z")

    def test_an_earlier_unparseable_maxed_window_does_not_stop_the_scan(self):
        # pins `continue`, not `break`, on the unparseable-reset guard
        snapshot = UsageSnapshot(
            five_hour=UsageWindow(100.0, "not-a-timestamp"),
            seven_day=UsageWindow(100.0, "2026-05-25T00:00:00Z"),
            scoped=(),
        )
        assert poll_policy.limiting_reset_epoch(snapshot) == poll_policy.parse_reset_epoch(
            "2026-05-25T00:00:00Z"
        )

    def test_none_snapshot_is_none(self):
        assert poll_policy.limiting_reset_epoch(None) is None


class TestEarliestFutureResetEpoch:
    def test_picks_the_soonest_future_reset(self):
        snapshot = UsageSnapshot(
            five_hour=UsageWindow(10.0, "2026-05-25T00:00:00Z"),
            seven_day=UsageWindow(10.0, "2026-05-20T00:00:00Z"),
            scoped=(),
        )
        now_s = poll_policy.parse_reset_epoch("2026-05-01T00:00:00Z")
        assert now_s is not None
        assert poll_policy.earliest_future_reset_epoch(
            snapshot, now_s
        ) == poll_policy.parse_reset_epoch("2026-05-20T00:00:00Z")

    def test_ignores_a_reset_in_the_past(self):
        past_reset = poll_policy.parse_reset_epoch("2026-05-01T00:00:00Z")
        assert past_reset is not None
        snapshot = UsageSnapshot(
            five_hour=UsageWindow(10.0, "2026-05-01T00:00:00Z"), seven_day=None, scoped=()
        )
        assert poll_policy.earliest_future_reset_epoch(snapshot, now_s=past_reset + 1.0) is None

    def test_a_reset_exactly_at_now_is_not_future(self):
        reset_s = poll_policy.parse_reset_epoch("2026-05-01T00:00:00Z")
        assert reset_s is not None
        snapshot = UsageSnapshot(
            five_hour=UsageWindow(10.0, "2026-05-01T00:00:00Z"), seven_day=None, scoped=()
        )
        assert poll_policy.earliest_future_reset_epoch(snapshot, now_s=reset_s) is None

    def test_models_are_forwarded(self):
        snapshot = _snapshot(scoped=(ScopedWindow("Fable", 10.0, "2026-05-25T00:00:00Z"),))
        assert poll_policy.earliest_future_reset_epoch(snapshot, now_s=0.0) is None
        assert poll_policy.earliest_future_reset_epoch(
            snapshot, now_s=0.0, models=("Fable",)
        ) == poll_policy.parse_reset_epoch("2026-05-25T00:00:00Z")

    def test_an_earlier_unparseable_window_does_not_stop_the_scan(self):
        # pins `continue`, not `break`, on the skip guard
        snapshot = UsageSnapshot(
            five_hour=UsageWindow(10.0, "not-a-timestamp"),
            seven_day=UsageWindow(10.0, "2026-05-25T00:00:00Z"),
            scoped=(),
        )
        assert poll_policy.earliest_future_reset_epoch(
            snapshot, now_s=0.0
        ) == poll_policy.parse_reset_epoch("2026-05-25T00:00:00Z")

    def test_none_snapshot_is_none(self):
        assert poll_policy.earliest_future_reset_epoch(None, now_s=0.0) is None


class TestPollDue:
    def test_an_unplanned_entry_is_due(self):
        # no prior fetch ever wrote a plan -> the first fetch is always due
        assert poll_policy.poll_due(None, NOW) is True

    def test_a_plan_past_its_deadline_is_due(self):
        assert poll_policy.poll_due(NOW - 1.0, NOW) is True

    def test_the_deadline_itself_is_due(self):
        # >=, not >: a plan that reaches its deadline fetches at that tick
        assert poll_policy.poll_due(NOW, NOW) is True

    def test_a_plan_still_waiting_is_not_due(self):
        assert poll_policy.poll_due(NOW + 60.0, NOW) is False


class TestEarliestResetEpoch:
    """Unlike earliest_future_reset_epoch, includes a reset already past —
    cache_trust.trust_ok needs the true earliest reset, not "no reset known"."""

    def test_picks_the_soonest_reset_regardless_of_past_or_future(self):
        snapshot = UsageSnapshot(
            five_hour=UsageWindow(10.0, "2026-05-25T00:00:00Z"),
            seven_day=UsageWindow(10.0, "2026-05-20T00:00:00Z"),
            scoped=(),
        )
        assert poll_policy.earliest_reset_epoch(snapshot) == poll_policy.parse_reset_epoch(
            "2026-05-20T00:00:00Z"
        )

    def test_includes_a_reset_already_in_the_past(self):
        snapshot = UsageSnapshot(
            five_hour=UsageWindow(10.0, "2026-05-01T00:00:00Z"), seven_day=None, scoped=()
        )
        assert poll_policy.earliest_reset_epoch(snapshot) == poll_policy.parse_reset_epoch(
            "2026-05-01T00:00:00Z"
        )

    def test_models_are_forwarded(self):
        snapshot = _snapshot(scoped=(ScopedWindow("Fable", 10.0, "2026-05-25T00:00:00Z"),))
        assert poll_policy.earliest_reset_epoch(snapshot) is None
        assert poll_policy.earliest_reset_epoch(
            snapshot, models=("Fable",)
        ) == poll_policy.parse_reset_epoch("2026-05-25T00:00:00Z")

    def test_an_earlier_unparseable_window_does_not_stop_the_scan(self):
        snapshot = UsageSnapshot(
            five_hour=UsageWindow(10.0, "not-a-timestamp"),
            seven_day=UsageWindow(10.0, "2026-05-25T00:00:00Z"),
            scoped=(),
        )
        assert poll_policy.earliest_reset_epoch(snapshot) == poll_policy.parse_reset_epoch(
            "2026-05-25T00:00:00Z"
        )

    def test_none_snapshot_is_none(self):
        assert poll_policy.earliest_reset_epoch(None) is None


class TestUrgentMode:
    """Urgent cadence: active + moving inside the escalation band.

    `URGENT_INTERVAL_S` fires only while the ACTIVE account is actually
    burning inside `threshold − ESCALATION_MARGIN_PCT`; a recent 429
    suppresses it entirely.
    """

    def test_active_moving_inside_the_band_polls_urgently(self):
        # arrange/act — prev 80 → new 82 is movement, and 82 ≥ 90 − 15
        _, interval = _plan(prev_pct=80.0, new_pct=82.0, is_active=True, threshold=90.0)

        # assert
        assert interval == poll_policy.URGENT_INTERVAL_S

    def test_inside_the_band_without_movement_stays_normal(self):
        # arrange/act — in band but unmoved: decay path, not urgent
        _, interval = _plan(
            prev_interval_s=180.0,
            prev_pct=82.0,
            new_pct=82.0,
            is_active=True,
            threshold=90.0,
        )

        # assert — the unmoved ×1.5 decay off the normal floor, not 60s
        assert interval == 270.0

    def test_outside_the_band_stays_normal(self):
        # arrange/act — moving but below the escalation band (74 < 75)
        _, interval = _plan(prev_pct=70.0, new_pct=74.0, is_active=True, threshold=90.0)

        # assert — plain movement halving floored at the normal minimum
        assert interval == poll_policy.MIN_INTERVAL_S

    def test_candidates_never_go_urgent(self):
        # arrange/act — same numbers but not the active account
        _, interval = _plan(prev_pct=80.0, new_pct=82.0, is_active=False, threshold=90.0)

        # assert — candidate movement floor, not urgent
        assert interval == poll_policy.MIN_INTERVAL_S

    def test_recent_429_suppresses_urgent(self):
        # arrange/act — every urgent condition plus an armed post-429 cadence
        _, interval = _plan(
            prev_pct=80.0, new_pct=82.0, is_active=True, threshold=90.0, recent_429=True
        )

        # assert — the AIMD floor takes over; urgent is suppressed entirely
        assert interval >= poll_policy.POST_429_MIN_INTERVAL_S

    def test_the_band_edge_is_inclusive(self):
        # arrange/act — new_pct exactly at threshold − margin
        _, interval = _plan(
            prev_pct=70.0,
            new_pct=90.0 - poll_policy.ESCALATION_MARGIN_PCT,
            is_active=True,
            threshold=90.0,
        )

        # assert
        assert interval == poll_policy.URGENT_INTERVAL_S

    def test_past_threshold_is_still_urgent(self):
        # arrange/act — burning over the threshold mid-tick before the switch lands
        _, interval = _plan(prev_pct=85.0, new_pct=91.0, is_active=True, threshold=90.0)

        # assert
        assert interval == poll_policy.URGENT_INTERVAL_S

    def test_unknown_pct_is_never_urgent(self):
        # arrange/act — nothing to judge movement on
        _, interval = _plan(prev_pct=None, new_pct=None, is_active=True, threshold=90.0)

        # assert — unknown → the plain active default
        assert interval == poll_policy.MIN_INTERVAL_S

    def test_exhausted_overrides_urgent(self):
        # arrange/act — at-limit (headroom 0): the bounded recovery probe wins
        _, interval = _plan(
            prev_pct=95.0, new_pct=100.0, is_active=True, threshold=90.0, headroom=0.0
        )

        # assert
        assert interval == poll_policy.EXHAUSTED_INTERVAL_S


def _entry(**kw: object) -> UsageCacheEntry:
    return replace(EMPTY_USAGE_CACHE_ENTRY, **kw)  # type: ignore[arg-type]


class TestPlanOversleepsInterval:
    """A next_poll_at beyond what the bounded planner could have written is an
    obsolete reset-parked plan — structurally detectable so a stale parked
    deadline cannot keep a usable account asleep."""

    def test_no_next_poll_is_not_overslept(self):
        # arrange
        entry = _entry(next_poll_at_s=None, poll_interval_s=300.0)

        # act/assert
        assert not poll_policy.plan_oversleeps_interval(entry, now_s=1000.0)

    def test_due_next_poll_is_not_overslept(self):
        # arrange — already past
        entry = _entry(next_poll_at_s=900.0, poll_interval_s=300.0)

        # act/assert
        assert not poll_policy.plan_oversleeps_interval(entry, now_s=1000.0)

    def test_next_poll_within_the_bounded_ceiling_is_not_overslept(self):
        # arrange — at the furthest a jittered plan past the floor could land
        interval = 1200.0
        ceiling = 1000.0 + interval * (1.0 + poll_policy.JITTER_FRAC) + poll_policy.RESET_SLACK_S
        entry = _entry(next_poll_at_s=ceiling, poll_interval_s=interval)

        # act/assert
        assert not poll_policy.plan_oversleeps_interval(entry, now_s=1000.0)

    def test_next_poll_beyond_the_bounded_ceiling_is_overslept(self):
        # arrange — one second past what a 1200s plan could have produced
        interval = 1200.0
        beyond = (
            1000.0 + interval * (1.0 + poll_policy.JITTER_FRAC) + poll_policy.RESET_SLACK_S + 1.0
        )
        entry = _entry(next_poll_at_s=beyond, poll_interval_s=interval)

        # act/assert
        assert poll_policy.plan_oversleeps_interval(entry, now_s=1000.0)

    def test_missing_interval_floors_at_the_exhausted_interval(self):
        # arrange — no learned interval: the exhausted floor is the bound
        beyond = (
            1000.0
            + poll_policy.EXHAUSTED_INTERVAL_S * (1.0 + poll_policy.JITTER_FRAC)
            + poll_policy.RESET_SLACK_S
            + 1.0
        )
        entry = _entry(next_poll_at_s=beyond, poll_interval_s=None)

        # act/assert
        assert poll_policy.plan_oversleeps_interval(entry, now_s=1000.0)

    def test_short_interval_still_uses_the_exhausted_floor(self):
        # arrange — interval below the floor can't shrink the bound under it
        within_floor = (
            1000.0
            + poll_policy.EXHAUSTED_INTERVAL_S * (1.0 + poll_policy.JITTER_FRAC)
            + poll_policy.RESET_SLACK_S
            - 1.0
        )
        entry = _entry(next_poll_at_s=within_floor, poll_interval_s=60.0)

        # act/assert
        assert not poll_policy.plan_oversleeps_interval(entry, now_s=1000.0)


class TestDueCandidate:
    """The due candidate with the stalest data, or None — shared by the engine
    and any other surface so all pick the same single alternate per pass."""

    def test_absent_entry_is_due_first(self):
        # arrange — "new" has no entry at all; "old" fetched long ago, due
        entries = {"old": _entry(fetched_at_s=100.0, next_poll_at_s=500.0)}

        # act/assert
        assert poll_policy.due_candidate(["new", "old"], entries, now_s=1000.0) == "new"

    def test_never_fetched_beats_fetched(self):
        # arrange — "blank" has an entry but no measurement yet
        entries = {
            "old": _entry(fetched_at_s=100.0, next_poll_at_s=500.0),
            "blank": _entry(fetched_at_s=None, next_poll_at_s=None),
        }

        # act/assert
        assert poll_policy.due_candidate(["old", "blank"], entries, now_s=1000.0) == "blank"

    def test_stalest_fetched_wins(self):
        # arrange
        entries = {
            "a": _entry(fetched_at_s=400.0, next_poll_at_s=500.0),
            "b": _entry(fetched_at_s=200.0, next_poll_at_s=500.0),
        }

        # act/assert
        assert poll_policy.due_candidate(["a", "b"], entries, now_s=1000.0) == "b"

    def test_not_due_is_skipped(self):
        # arrange — both plans still in the future (a 1200s learned interval
        # puts 2000 inside the bounded ceiling, so neither is overslept)
        entries = {
            "a": _entry(fetched_at_s=400.0, next_poll_at_s=2000.0, poll_interval_s=1200.0),
            "b": _entry(fetched_at_s=200.0, next_poll_at_s=2000.0, poll_interval_s=1200.0),
        }

        # act/assert
        assert poll_policy.due_candidate(["a", "b"], entries, now_s=1000.0) is None

    def test_overslept_plan_counts_as_due(self):
        # arrange — next_poll far beyond the bounded ceiling: a parked plan
        far = (
            1000.0
            + poll_policy.EXHAUSTED_INTERVAL_S * (1.0 + poll_policy.JITTER_FRAC)
            + poll_policy.RESET_SLACK_S
            + 100.0
        )
        entries = {"a": _entry(fetched_at_s=100.0, next_poll_at_s=far, poll_interval_s=300.0)}

        # act/assert
        assert poll_policy.due_candidate(["a"], entries, now_s=1000.0) == "a"

    def test_backoff_is_excluded(self):
        # arrange — armed 429 backoff outranks a due plan
        entries = {
            "a": _entry(fetched_at_s=100.0, next_poll_at_s=500.0, backoff_until_s=1500.0),
            "b": _entry(fetched_at_s=200.0, next_poll_at_s=500.0),
        }

        # act/assert
        assert poll_policy.due_candidate(["a", "b"], entries, now_s=1000.0) == "b"

    def test_expired_backoff_does_not_exclude(self):
        # arrange — backoff in the past: eligible again
        entries = {
            "a": _entry(fetched_at_s=100.0, next_poll_at_s=500.0, backoff_until_s=900.0),
        }

        # act/assert
        assert poll_policy.due_candidate(["a"], entries, now_s=1000.0) == "a"

    def test_no_candidates_returns_none(self):
        # act/assert
        assert poll_policy.due_candidate([], {}, now_s=1000.0) is None

    def test_absent_beats_never_fetched_regardless_of_name(self):
        # arrange — "a" absent, "b" present-but-never-fetched: the tier-0 tie
        # breaks on name; an absent row must stay tier 0, not jump a tier
        entries = {"b": _entry(fetched_at_s=None, next_poll_at_s=None)}

        # act/assert
        assert poll_policy.due_candidate(["a", "b"], entries, now_s=1000.0) == "a"

    def test_never_fetched_beats_absent_when_its_name_sorts_first(self):
        # arrange — "z" absent, "a" never-fetched: both tier 0, "a" wins the
        # name tiebreak — and an absent row must not end the scan early
        entries = {"a": _entry(fetched_at_s=None, next_poll_at_s=None)}

        # act/assert
        assert poll_policy.due_candidate(["z", "a"], entries, now_s=1000.0) == "a"

    def test_not_due_entry_does_not_end_the_scan(self):
        # arrange — a not-due first candidate must not hide a due later one
        entries = {
            "a": _entry(fetched_at_s=400.0, next_poll_at_s=2000.0, poll_interval_s=1200.0),
            "b": _entry(fetched_at_s=200.0, next_poll_at_s=500.0),
        }

        # act/assert
        assert poll_policy.due_candidate(["a", "b"], entries, now_s=1000.0) == "b"
