"""``poll_policy`` — reset epochs and the urgent-mode band.

Binding-pct selection, reset-epoch parsing/limiting/earliest-future math,
poll-due checks, and the threshold-driven urgent band the auto loop's
scheduler escalates through.
"""

import pytest
from support.poll_rigs import NOW
from support.poll_rigs import plan as _plan
from support.poll_rigs import poll_snapshot as _snapshot

from claude_acc_manager.usage.domain.services import poll_policy
from claude_acc_manager.usage.domain.usage_snapshot import (
    ScopedWindow,
    UsageSnapshot,
    UsageWindow,
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
