"""``auto_rank`` — trigger classification, cooldown, and recovery gating.

The guards that decide *whether* a switch should even be considered:
cooldown windows, every-account-above-threshold, binding-recovery epochs,
and whether a recovery is actually useful.
"""

from support.rank_requests import NOW_S
from support.rank_requests import snap as _snap

from claude_acc_manager.auto.domain.auto_state import EMPTY_AUTO_STATE, AutoState
from claude_acc_manager.auto.domain.services import auto_rank


class TestClassifyTrigger:
    def test_unknown_active_is_none(self):
        assert auto_rank.classify_trigger(None, 90.0) is None

    def test_below_threshold(self):
        # 20 pts headroom → 80% utilization < 90
        assert auto_rank.classify_trigger(20.0, 90.0) == "below"

    def test_at_threshold_is_proactive(self):
        # exactly at the threshold still triggers (escape before the wall)
        assert auto_rank.classify_trigger(10.0, 90.0) == "proactive"

    def test_one_point_below_threshold_is_below(self):
        # 11 pts headroom → 89% < 90 — sits just under the boundary
        assert auto_rank.classify_trigger(11.0, 90.0) == "below"

    def test_sub_one_headroom_is_proactive(self):
        # 0.5 pts → 99.5% utilized, but not at the wall yet
        assert auto_rank.classify_trigger(0.5, 90.0) == "proactive"

    def test_zero_headroom_is_at_limit(self):
        assert auto_rank.classify_trigger(0.0, 90.0) == "at-limit"
        assert auto_rank.classify_trigger(-5.0, 90.0) == "at-limit"


class TestInCooldown:
    def test_never_switched_is_not_in_cooldown(self):
        assert not auto_rank.in_cooldown(EMPTY_AUTO_STATE, NOW_S, 300.0)

    def test_within_cooldown(self):
        state = AutoState(last_switch_at_s=NOW_S - 60.0)
        assert auto_rank.in_cooldown(state, NOW_S, 300.0)

    def test_past_cooldown(self):
        state = AutoState(last_switch_at_s=NOW_S - 301.0)
        assert not auto_rank.in_cooldown(state, NOW_S, 300.0)

    def test_exactly_at_cooldown_releases(self):
        # the cooldown is exclusive — elapsed == cooldown is out of it
        state = AutoState(last_switch_at_s=NOW_S - 300.0)
        assert not auto_rank.in_cooldown(state, NOW_S, 300.0)

    def test_zero_cooldown_is_never_in_cooldown(self):
        state = AutoState(last_switch_at_s=NOW_S - 0.1)
        assert not auto_rank.in_cooldown(state, NOW_S, 0.0)


class TestBindingRecoveryEpoch:
    def test_binding_window_is_the_highest_pct(self):
        # 7d binds at 95; its (far) reset wins over the 5h's nearer one
        snap = _snap(40.0, NOW_S + 3600.0, 95.0, NOW_S + 86400.0)
        assert auto_rank.binding_recovery_epoch(snap, NOW_S) == NOW_S + 86400.0

    def test_binding_window_is_pct_ordered_not_label_ordered(self):
        # 5h binds at 95 — tuple order ("5h" < "7d") or reset order would
        # pick the 7d window instead; only pct order picks 5h
        snap = _snap(95.0, NOW_S + 3600.0, 40.0, NOW_S + 86400.0)
        assert auto_rank.binding_recovery_epoch(snap, NOW_S) == NOW_S + 3600.0

    def test_past_reset_is_infinite(self):
        snap = _snap(95.0, NOW_S - 10.0)
        assert auto_rank.binding_recovery_epoch(snap, NOW_S) == float("inf")

    def test_reset_exactly_now_is_infinite(self):
        # a reset at this instant is already in the past for ordering purposes
        snap = _snap(95.0, NOW_S)
        assert auto_rank.binding_recovery_epoch(snap, NOW_S) == float("inf")

    def test_missing_reset_is_infinite(self):
        snap = _snap(95.0, None)
        assert auto_rank.binding_recovery_epoch(snap, NOW_S) == float("inf")

    def test_no_snapshot_is_infinite(self):
        assert auto_rank.binding_recovery_epoch(None, NOW_S) == float("inf")


class TestEveryAccountAboveThreshold:
    def test_all_measured_at_threshold(self):
        headroom = {"a": 5.0, "b": 8.0}
        assert auto_rank.every_account_above_threshold(["a", "b"], headroom, 4.0, 90.0)

    def test_one_healthy_candidate_defeats_it(self):
        headroom = {"a": 5.0, "b": 50.0}
        assert not auto_rank.every_account_above_threshold(["a", "b"], headroom, 4.0, 90.0)

    def test_unknown_active_defeats_it(self):
        assert not auto_rank.every_account_above_threshold(["a"], {"a": 1.0}, None, 90.0)

    def test_no_measured_candidate_defeats_it(self):
        assert not auto_rank.every_account_above_threshold(["a"], {}, 4.0, 90.0)

    def test_healthy_active_defeats_it(self):
        # active at 80% — not a spent-fleet state no matter the candidates
        assert not auto_rank.every_account_above_threshold(["a"], {"a": 5.0}, 20.0, 90.0)

    def test_active_one_point_under_defeats_it(self):
        # active at 89% — one point of headroom under the threshold
        assert not auto_rank.every_account_above_threshold(["a"], {"a": 5.0}, 11.0, 90.0)

    def test_active_exactly_at_threshold_is_spent(self):
        # active at exactly 90% counts — the threshold is inclusive here
        assert auto_rank.every_account_above_threshold(["a"], {"a": 5.0}, 10.0, 90.0)

    def test_candidate_one_point_under_defeats_it(self):
        assert not auto_rank.every_account_above_threshold(["a"], {"a": 11.0}, 5.0, 90.0)

    def test_candidate_exactly_at_threshold_counts(self):
        assert auto_rank.every_account_above_threshold(["a"], {"a": 10.0}, 5.0, 90.0)


class TestRecoveryIsUseful:
    """Axis selection: spent fleet OR either reset inside the 4h horizon."""

    def test_fully_spent_fleet_uses_recovery_axis(self):
        # exactly 3.0 pts on both sides still counts as spent — the bound is
        # inclusive on both conjuncts
        assert auto_rank.recovery_is_useful(NOW_S + 100_000.0, NOW_S + 200_000.0, 3.0, 3.0, NOW_S)

    def test_one_unspent_side_defeats_the_spent_leg(self):
        # active spent but best candidate at 10 pts — not a spent fleet;
        # both resets far past the horizon → headroom axis
        assert not auto_rank.recovery_is_useful(
            NOW_S + 100_000.0, NOW_S + 200_000.0, 3.0, 10.0, NOW_S
        )

    def test_candidate_inside_horizon_uses_recovery_axis(self):
        assert auto_rank.recovery_is_useful(NOW_S + 3600.0, NOW_S + 200_000.0, 10.0, 20.0, NOW_S)

    def test_active_inside_horizon_uses_recovery_axis(self):
        assert auto_rank.recovery_is_useful(NOW_S + 200_000.0, NOW_S + 3600.0, 10.0, 20.0, NOW_S)

    def test_both_outside_horizon_uses_headroom_axis(self):
        assert not auto_rank.recovery_is_useful(
            NOW_S + 100_000.0, NOW_S + 200_000.0, 10.0, 20.0, NOW_S
        )

    def test_candidate_exactly_at_horizon_counts(self):
        assert auto_rank.recovery_is_useful(NOW_S + 14_400.0, NOW_S + 200_000.0, 10.0, 20.0, NOW_S)

    def test_active_exactly_at_horizon_counts(self):
        assert auto_rank.recovery_is_useful(NOW_S + 200_000.0, NOW_S + 14_400.0, 10.0, 20.0, NOW_S)

    def test_one_side_outside_one_inside_is_enough(self):
        # the or — only one side needs to be inside the horizon
        assert auto_rank.recovery_is_useful(NOW_S + 200_000.0, NOW_S + 3600.0, 10.0, 20.0, NOW_S)
