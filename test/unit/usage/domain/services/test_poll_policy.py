"""Unit tests for usage.domain.services.poll_policy.

Ports claude-swap poll_policy.py's plan_after_fetch tests
(research_repos/claude-swap/tests/test_poll_policy.py) onto our signature,
which takes an already-extracted binding pct (from headroom.account_headroom)
rather than a raw usage dict, and drops threshold/urgent-mode (M5 plan
decision 1 — deferred to M9, the auto loop that actually owns a threshold).
"""

import itertools

import pytest

from claude_acc_manager.usage.domain.services import poll_policy
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

    Measured 2026-07-11 (claude-swap probe3): a rolling ~60-minute window of
    ~28-30 requests per identity for non-first-party User-Agents — not a
    refilling bucket, so a saturated window needs up to 60 minutes to
    recover. This is the M5 milestone's required budget-arithmetic test
    (docs/plan.md §9).
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
