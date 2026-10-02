"""auto_rank: trigger classification, cooldown, no-return guard, candidate ranking."""

import dataclasses
from datetime import UTC, datetime

from claude_acc_manager.auto.domain.auto_state import EMPTY_AUTO_STATE, AutoState
from claude_acc_manager.auto.domain.services import auto_rank
from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot, UsageWindow

NOW_S = 1_700_000_000.0


def _iso(epoch_s: float) -> str:
    return datetime.fromtimestamp(epoch_s, tz=UTC).isoformat()


def _snap(
    five_pct: float | None = None,
    five_reset_s: float | None = None,
    seven_pct: float | None = None,
    seven_reset_s: float | None = None,
):
    """A snapshot from window pct + reset epoch seconds (None window = absent)."""
    five = (
        UsageWindow(pct=five_pct, resets_at=_iso(five_reset_s) if five_reset_s else None)
        if five_pct is not None
        else None
    )
    seven = (
        UsageWindow(pct=seven_pct, resets_at=_iso(seven_reset_s) if seven_reset_s else None)
        if seven_pct is not None
        else None
    )
    return UsageSnapshot(five_hour=five, seven_day=seven, scoped=())


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


class TestRankCandidates:
    """Proactive ranking on the headroom axis (the ordinary case)."""

    def _snapshots(self):
        return {"a": _snap(50.0), "b": _snap(50.0), "c": _snap(50.0)}

    def test_best_picks_highest_headroom(self):
        ordered, any_known = auto_rank.rank_candidates(
            "proactive",
            ["a", "b"],
            self._snapshots(),
            {"a": 30.0, "b": 60.0},
            active="c",
            active_headroom=5.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            now_s=NOW_S,
            no_return=None,
        )
        assert ordered == ["b", "a"]
        assert any_known

    def test_best_requires_the_hysteresis_margin(self):
        # active 5 pts; a at 12 (7 over — under 10) is refused; b at 20 qualifies
        ordered, _ = auto_rank.rank_candidates(
            "proactive",
            ["a", "b"],
            self._snapshots(),
            {"a": 12.0, "b": 20.0},
            active="c",
            active_headroom=5.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            now_s=NOW_S,
            no_return=None,
        )
        assert ordered == ["b"]

    def test_candidate_at_threshold_cannot_be_a_proactive_landing(self):
        # b at 92% (8 pts) — healthy peers only; a at 40 pts qualifies
        ordered, _ = auto_rank.rank_candidates(
            "proactive",
            ["a", "b"],
            self._snapshots(),
            {"a": 40.0, "b": 8.0},
            active="c",
            active_headroom=5.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            now_s=NOW_S,
            no_return=None,
        )
        assert ordered == ["a"]

    def test_unknown_and_exhausted_candidates_are_skipped(self):
        ordered, any_known = auto_rank.rank_candidates(
            "proactive",
            ["a", "b", "c"],
            self._snapshots(),
            {"a": 30.0, "b": 0.0},  # c unmeasured
            active="d",
            active_headroom=5.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            now_s=NOW_S,
            no_return=None,
        )
        assert ordered == ["a"]
        assert any_known

    def test_unmeasured_first_candidate_does_not_stop_the_scan(self):
        # the unknown entry must be skipped, not terminate the loop
        ordered, any_known = auto_rank.rank_candidates(
            "proactive",
            ["u", "a"],
            self._snapshots(),
            {"a": 50.0},  # u unmeasured
            active="c",
            active_headroom=5.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            now_s=NOW_S,
            no_return=None,
        )
        assert ordered == ["a"]
        assert any_known

    def test_equal_keys_keep_registry_order(self):
        # a key-tie must not re-sort by name — registry order wins
        ordered, _ = auto_rank.rank_candidates(
            "proactive",
            ["z", "a"],
            self._snapshots(),
            {"a": 50.0, "z": 50.0},
            active="c",
            active_headroom=5.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            now_s=NOW_S,
            no_return=None,
        )
        assert ordered == ["z", "a"]

    def test_nothing_known_reports_any_known_false(self):
        ordered, any_known = auto_rank.rank_candidates(
            "proactive",
            ["a", "b"],
            self._snapshots(),
            {},
            active="d",
            active_headroom=5.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            now_s=NOW_S,
            no_return=None,
        )
        assert ordered == []
        assert any_known is False

    def test_no_return_bars_the_account_we_left(self):
        ordered, _ = auto_rank.rank_candidates(
            "proactive",
            ["a", "b"],
            self._snapshots(),
            {"a": 60.0, "b": 30.0},
            active="c",
            active_headroom=5.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            now_s=NOW_S,
            no_return="a",
        )
        assert ordered == ["b"]

    def test_next_available_keeps_registry_order(self):
        ordered, _ = auto_rank.rank_candidates(
            "proactive",
            ["a", "b"],
            self._snapshots(),
            {"a": 30.0, "b": 60.0},
            active="c",
            active_headroom=5.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="next-available",
            now_s=NOW_S,
            no_return=None,
        )
        # rotation semantics: first eligible, not highest headroom
        assert ordered == ["a", "b"]

    def test_at_limit_skips_the_hysteresis_margin(self):
        ordered, _ = auto_rank.rank_candidates(
            "at-limit",
            ["a"],
            self._snapshots(),
            {"a": 1.0},
            active="c",
            active_headroom=0.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            now_s=NOW_S,
            no_return="a",  # the escape also ignores the no-return bar
        )
        assert ordered == ["a"]

    def test_at_limit_still_refuses_zero_headroom(self):
        # escape or not, a fully dead account cannot take the session
        ordered, _ = auto_rank.rank_candidates(
            "at-limit",
            ["a"],
            self._snapshots(),
            {"a": 0.0},
            active="c",
            active_headroom=0.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            now_s=NOW_S,
            no_return=None,
        )
        assert ordered == []

    def test_at_limit_next_available_keeps_registry_order(self):
        ordered, _ = auto_rank.rank_candidates(
            "at-limit",
            ["a", "b"],
            self._snapshots(),
            {"a": 10.0, "b": 50.0},
            active="c",
            active_headroom=0.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="next-available",
            now_s=NOW_S,
            no_return=None,
        )
        # rotation order wins even though b has more headroom
        assert ordered == ["a", "b"]

    def test_below_trigger_admits_without_margins(self):
        ordered, _ = auto_rank.rank_candidates(
            "below",
            ["a"],
            self._snapshots(),
            {"a": 2.0},
            active="c",
            active_headroom=50.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            now_s=NOW_S,
            no_return=None,
        )
        assert ordered == ["a"]

    def test_landing_one_point_below_threshold_is_admitted(self):
        # 89% utilized — just under the landing ceiling. active_headroom is
        # None: any measured-but-healthy active would make the margin fail
        # anyway, so the landing check is only distinguishable unmeasured
        ordered, _ = auto_rank.rank_candidates(
            "proactive",
            ["a"],
            self._snapshots(),
            {"a": 11.0},
            active="c",
            active_headroom=None,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            now_s=NOW_S,
            no_return=None,
        )
        assert ordered == ["a"]

    def test_landing_exactly_at_threshold_is_refused(self):
        ordered, _ = auto_rank.rank_candidates(
            "proactive",
            ["a"],
            self._snapshots(),
            {"a": 10.0},
            active="c",
            active_headroom=None,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            now_s=NOW_S,
            no_return=None,
        )
        assert ordered == []

    def test_margin_exactly_at_hysteresis_admits(self):
        # h - active == hysteresis_pct meets the margin — it is exclusive
        ordered, _ = auto_rank.rank_candidates(
            "proactive",
            ["a"],
            self._snapshots(),
            {"a": 15.0},
            active="c",
            active_headroom=5.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            now_s=NOW_S,
            no_return=None,
        )
        assert ordered == ["a"]

    def test_margin_just_under_hysteresis_refuses(self):
        ordered, _ = auto_rank.rank_candidates(
            "proactive",
            ["a"],
            self._snapshots(),
            {"a": 14.0},
            active="c",
            active_headroom=5.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            now_s=NOW_S,
            no_return=None,
        )
        assert ordered == []

    def test_unknown_active_headroom_skips_the_margin(self):
        # active_headroom=None → no margin comparison — admission by landing only
        ordered, _ = auto_rank.rank_candidates(
            "proactive",
            ["a"],
            self._snapshots(),
            {"a": 12.0},
            active="c",
            active_headroom=None,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            now_s=NOW_S,
            no_return=None,
        )
        assert ordered == ["a"]

    def test_margin_not_applied_under_next_available(self):
        # rotation does not demand a headroom margin
        ordered, _ = auto_rank.rank_candidates(
            "proactive",
            ["a"],
            self._snapshots(),
            {"a": 12.0},
            active="c",
            active_headroom=5.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="next-available",
            now_s=NOW_S,
            no_return=None,
        )
        assert ordered == ["a"]


class TestRecoveryAxis:
    """All measured accounts ≥ threshold → rank by soonest binding reset."""

    def _snapshots(self):
        return {
            "a": _snap(95.0, NOW_S + 3600.0),  # back in 1h
            "b": _snap(96.0, NOW_S + 7200.0),  # back in 2h
            "c": _snap(97.0, NOW_S + 10800.0),  # active: back in 3h
        }

    def test_soonest_recovery_wins(self):
        ordered, any_known = auto_rank.rank_candidates(
            "proactive",
            ["a", "b"],
            self._snapshots(),
            {"a": 5.0, "b": 4.0},
            active="c",
            active_headroom=3.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            now_s=NOW_S,
            no_return=None,
        )
        assert ordered == ["a", "b"]
        assert any_known

    def test_recovery_axis_needs_the_hysteresis_margin(self):
        # a returns only 100s sooner than the active — under 300s hysteresis
        snapshots = {"a": _snap(95.0, NOW_S + 3500.0), "c": _snap(97.0, NOW_S + 3600.0)}
        ordered, _ = auto_rank.rank_candidates(
            "proactive",
            ["a"],
            snapshots,
            {"a": 5.0},
            active="c",
            active_headroom=3.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            now_s=NOW_S,
            no_return=None,
        )
        assert ordered == []

    def test_recovery_axis_margin_is_strictly_before(self):
        # a returns exactly 300s sooner than the active — on the boundary,
        # the hysteresis refuses the move
        snapshots = {"a": _snap(95.0, NOW_S + 3300.0), "c": _snap(97.0, NOW_S + 3600.0)}
        ordered, _ = auto_rank.rank_candidates(
            "proactive",
            ["a"],
            snapshots,
            {"a": 5.0},
            active="c",
            active_headroom=3.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            now_s=NOW_S,
            no_return=None,
        )
        assert ordered == []

    def test_spent_check_uses_the_best_candidate_not_any(self):
        # b is spent (2 ≤ 3) but a is not (5 > 3) and every reset sits past
        # the 4h horizon — the axis stays headroom and a qualifies outright
        # (5 ≥ 2x2). A "min" census would dip into the spent band, take the
        # recovery axis, and refuse a on the hysteresis gate.
        snapshots = {
            "a": _snap(95.0, NOW_S + 50_000.0),
            "b": _snap(98.0, NOW_S + 60_000.0),
            "c": _snap(98.0, NOW_S + 40_000.0),
        }
        ordered, _ = auto_rank.rank_candidates(
            "proactive",
            ["a", "b"],
            snapshots,
            {"a": 5.0, "b": 2.0},
            active="c",
            active_headroom=2.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            now_s=NOW_S,
            no_return=None,
        )
        assert ordered == ["a"]

    def test_recovery_axis_tie_breaks_on_headroom(self):
        # same reset → the higher-headroom account wins within the axis
        snapshots = {
            "a": _snap(95.0, NOW_S + 3600.0),
            "b": _snap(92.0, NOW_S + 3600.0),
            "c": _snap(97.0, NOW_S + 200_000.0),
        }
        ordered, _ = auto_rank.rank_candidates(
            "proactive",
            ["a", "b"],
            snapshots,
            {"a": 5.0, "b": 8.0},
            active="c",
            active_headroom=3.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            now_s=NOW_S,
            no_return=None,
        )
        assert ordered == ["b", "a"]

    def test_recovery_axis_outranks_headroom_axis(self):
        # a returns inside the horizon (recovery axis); b only qualifies on
        # raw headroom (reset past the horizon) — recovery sorts first
        snapshots = {
            "a": _snap(95.0, NOW_S + 3600.0),
            "b": _snap(91.0, NOW_S + 200_000.0),
            "c": _snap(97.0, NOW_S + 300_000.0),
        }
        ordered, _ = auto_rank.rank_candidates(
            "proactive",
            ["a", "b"],
            snapshots,
            {"a": 5.0, "b": 10.0},
            active="c",
            active_headroom=5.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            now_s=NOW_S,
            no_return=None,
        )
        assert ordered == ["a", "b"]

    def test_two_headroom_qualifiers_order_by_headroom(self):
        # both resets past the horizon → pure headroom ordering
        snapshots = {
            "a": _snap(92.0, NOW_S + 200_000.0),
            "b": _snap(95.0, NOW_S + 210_000.0),
            "c": _snap(98.0, NOW_S + 300_000.0),
        }
        ordered, _ = auto_rank.rank_candidates(
            "proactive",
            ["a", "b"],
            snapshots,
            {"a": 8.0, "b": 5.0},
            active="c",
            active_headroom=2.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            now_s=NOW_S,
            no_return=None,
        )
        assert ordered == ["a", "b"]

    def test_peer_exactly_at_the_ratio_qualifies(self):
        # h == active * 2 meets the bound — not a margin failure
        snapshots = {
            "a": _snap(92.0, NOW_S + 200_000.0),
            "c": _snap(95.0, NOW_S + 300_000.0),
        }
        ordered, _ = auto_rank.rank_candidates(
            "proactive",
            ["a"],
            snapshots,
            {"a": 10.0},
            active="c",
            active_headroom=5.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            now_s=NOW_S,
            no_return=None,
        )
        assert ordered == ["a"]

    def test_headroom_axis_admits_when_active_is_fully_spent(self):
        # active at 0 → the ratio bound is h >= 0; any candidate qualifies —
        # and a weaker fallback-only peer still joins the ordered list
        snapshots = {
            "a": _snap(99.0, NOW_S + 200_000.0),
            "b": _snap(95.0, NOW_S + 50_000.0),
            "c": _snap(100.0, NOW_S + 300_000.0),
        }
        ordered, _ = auto_rank.rank_candidates(
            "proactive",
            ["a", "b"],
            snapshots,
            {"a": 1.0, "b": 5.0},
            active="c",
            active_headroom=0.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            now_s=NOW_S,
            no_return=None,
        )
        assert ordered == ["b", "a"]

    def test_headroom_axis_is_not_the_spent_leg(self):
        # active at 5 with a candidate at 3 pts — not a spent fleet, resets
        # far → headroom axis; 3 < 5x2 → fallback, which needs a spent active
        snapshots = {
            "a": _snap(97.0, NOW_S + 50_000.0),
            "c": _snap(95.0, NOW_S + 200_000.0),
        }
        ordered, _ = auto_rank.rank_candidates(
            "proactive",
            ["a"],
            snapshots,
            {"a": 3.0},
            active="c",
            active_headroom=5.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            now_s=NOW_S,
            no_return=None,
        )
        assert ordered == []

    def test_headroom_axis_when_resets_are_past_the_horizon(self):
        # Both resets days out → ratio gate: peer needs >= active x 2 headroom
        snapshots = {
            "a": _snap(92.0, NOW_S + 200_000.0),
            "c": _snap(97.0, NOW_S + 300_000.0),
        }
        ordered, _ = auto_rank.rank_candidates(
            "proactive",
            ["a"],
            snapshots,
            {"a": 8.0},  # 8 >= 3x2=6 — dominates on headroom
            active="c",
            active_headroom=3.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            now_s=NOW_S,
            no_return=None,
        )
        assert ordered == ["a"]

    def test_far_out_peer_below_the_ratio_is_refused(self):
        snapshots = {
            "a": _snap(96.0, NOW_S + 200_000.0),
            "c": _snap(95.0, NOW_S + 300_000.0),
        }
        ordered, _ = auto_rank.rank_candidates(
            "proactive",
            ["a"],
            snapshots,
            {"a": 4.0},  # 4 < 5x2=10 — not enough to move for
            active="c",
            active_headroom=5.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            now_s=NOW_S,
            no_return=None,
        )
        assert ordered == []


class TestSpentFallback:
    """Margin failures under all_above — re-admitted only when both sides
    are spent and the candidate's reset lands strictly sooner."""

    def _rank(self, candidates, snapshots, headroom, active_headroom=3.0):
        return auto_rank.rank_candidates(
            "proactive",
            candidates,
            snapshots,
            headroom,
            active="c",
            active_headroom=active_headroom,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            now_s=NOW_S,
            no_return=None,
        )

    def test_fallback_readmits_a_sooner_reset(self):
        # a at 5 pts < 3x2 — margin failure; both spent, reset 50000s out vs
        # the active's 200000 — re-admitted on the fallback axis
        snapshots = {
            "a": _snap(95.0, NOW_S + 50_000.0),
            "c": _snap(97.0, NOW_S + 200_000.0),
        }
        ordered, _ = self._rank(["a"], snapshots, {"a": 5.0})
        assert ordered == ["a"]

    def test_fallback_requires_a_spent_active(self):
        # active at 5 pts — not spent → the fallback never engages
        snapshots = {
            "a": _snap(92.0, NOW_S + 50_000.0),
            "c": _snap(95.0, NOW_S + 200_000.0),
        }
        ordered, _ = self._rank(["a"], snapshots, {"a": 8.0}, active_headroom=5.0)
        assert ordered == []

    def test_fallback_requires_candidate_at_least_active_headroom(self):
        # a at 2 pts is BELOW the active's 3 — no reason to move
        snapshots = {
            "a": _snap(98.0, NOW_S + 50_000.0),
            "b": _snap(95.0, NOW_S + 60_000.0),
            "c": _snap(97.0, NOW_S + 200_000.0),
        }
        ordered, _ = self._rank(["a", "b"], snapshots, {"a": 2.0, "b": 5.0})
        assert ordered == ["b"]

    def test_fallback_boundary_headroom_equals_active(self):
        # h == active is a real (if tiny) improvement — admitted; b at 5 pts
        # is below the 3x2 ratio and falls back with a later reset
        snapshots = {
            "a": _snap(97.0, NOW_S + 50_000.0),
            "b": _snap(95.0, NOW_S + 60_000.0),
            "c": _snap(97.0, NOW_S + 200_000.0),
        }
        ordered, _ = self._rank(["a", "b"], snapshots, {"a": 3.0, "b": 5.0})
        assert ordered == ["a", "b"]

    def test_fallback_requires_strictly_sooner_reset(self):
        # reset exactly 300s sooner — on the hysteresis boundary, refused
        snapshots = {
            "a": _snap(95.0, NOW_S + 199_700.0),
            "c": _snap(97.0, NOW_S + 200_000.0),
        }
        ordered, _ = self._rank(["a"], snapshots, {"a": 5.0})
        assert ordered == []

    def test_fallback_refuses_a_later_reset(self):
        # a's reset lands AFTER the active's — the -300s margin, not +300s
        snapshots = {
            "a": _snap(95.0, NOW_S + 200_100.0),
            "c": _snap(97.0, NOW_S + 200_000.0),
        }
        ordered, _ = self._rank(["a"], snapshots, {"a": 5.0})
        assert ordered == []

    def test_fallbacks_order_by_recovery_then_headroom(self):
        snapshots = {
            "a": _snap(96.0, NOW_S + 50_000.0),
            "b": _snap(95.0, NOW_S + 50_000.0),
            "c": _snap(97.0, NOW_S + 200_000.0),
        }
        ordered, _ = self._rank(["a", "b"], snapshots, {"a": 4.0, "b": 5.0})
        # same reset → more headroom first
        assert ordered == ["b", "a"]

    def test_fallback_loses_to_any_qualifying_candidate(self):
        # q qualifies outright on headroom (7 >= 3x2); f only falls back —
        # the fallback pool is consulted only when qualifying is empty
        snapshots = {
            "f": _snap(95.0, NOW_S + 50_000.0),
            "q": _snap(93.0, NOW_S + 180_000.0),
            "c": _snap(97.0, NOW_S + 200_000.0),
        }
        ordered, _ = self._rank(["f", "q"], snapshots, {"f": 5.0, "q": 7.0})
        assert ordered == ["q"]


class TestNoReturnAccount:
    def _state(self, **kw) -> AutoState:
        base = AutoState(
            last_switch_at_s=NOW_S - 400.0,
            last_switch_from="a",
            last_switch_to="c",
            left_headroom=4.0,
            left_recovery_at_s=NOW_S + 100_000.0,
        )
        return dataclasses.replace(base, **kw)

    def test_bars_the_account_we_left(self):
        state = self._state()
        barred = auto_rank.no_return_account(
            "proactive", state, "c", {"a": 4.0}, {"a": _snap(95.0)}, 3.0, 90.0, NOW_S
        )
        assert barred == "a"

    def test_at_limit_never_bars(self):
        state = self._state()
        assert (
            auto_rank.no_return_account(
                "at-limit", state, "c", {"a": 4.0}, {"a": _snap(95.0)}, 0.0, 90.0, NOW_S
            )
            is None
        )

    def test_below_trigger_never_bars(self):
        state = self._state()
        assert (
            auto_rank.no_return_account(
                "below", state, "c", {"a": 4.0}, {"a": _snap(95.0)}, 30.0, 90.0, NOW_S
            )
            is None
        )

    def test_no_departure_record_means_no_bar(self):
        assert (
            auto_rank.no_return_account(
                "proactive", EMPTY_AUTO_STATE, "c", {}, {}, 3.0, 90.0, NOW_S
            )
            is None
        )

    def test_manual_move_off_the_landing_releases_the_bar(self):
        # Engine put us on "c"; user moved to "d" — the move is already undone
        state = self._state()
        assert (
            auto_rank.no_return_account(
                "proactive", state, "d", {"a": 4.0}, {"a": _snap(95.0)}, 3.0, 90.0, NOW_S
            )
            is None
        )

    def test_recovered_peer_is_released(self):
        # Left at 4 pts; now at 30 — beat the departure baseline + SPENT
        state = self._state()
        assert (
            auto_rank.no_return_account(
                "proactive",
                state,
                "c",
                {"a": 30.0},
                {"a": _snap(50.0, NOW_S + 3600.0)},
                3.0,
                90.0,
                NOW_S,
            )
            is None
        )

    def test_recovered_peer_beating_the_ratio_is_released(self):
        # Recovery leg fires (reset improved by >300s), then the peer at 8
        # pts beats the burned-down active (1.5) by the 2x ratio → release
        state = self._state(left_headroom=6.0, left_recovery_at_s=NOW_S + 200_000.0)
        assert (
            auto_rank.no_return_account(
                "proactive",
                state,
                "c",
                {"a": 8.0},
                {"a": _snap(92.0, NOW_S + 100_000.0)},
                1.5,
                90.0,
                NOW_S,
            )
            is None
        )

    def test_recovered_but_unmeasured_peer_stays_barred(self):
        # Recovery proven only by the reset leg; with no current headroom the
        # dominance check cannot run — no release
        state = self._state()
        assert (
            auto_rank.no_return_account(
                "proactive",
                state,
                "c",
                {},
                {"a": _snap(95.0, NOW_S + 50_000.0)},
                3.0,
                90.0,
                NOW_S,
            )
            == "a"
        )

    def test_peer_exactly_at_the_ratio_releases(self):
        # left 10 pts vs active 5 — exactly 2x — meets the release bound
        state = self._state()
        assert (
            auto_rank.no_return_account(
                "proactive", state, "c", {"a": 10.0}, {"a": _snap(93.0)}, 5.0, 90.0, NOW_S
            )
            is None
        )

    def test_peer_under_the_ratio_stays_barred(self):
        # left 10 pts vs active 10 — recovered, but 10 < 2x10 — not better outright
        state = self._state()
        assert (
            auto_rank.no_return_account(
                "proactive", state, "c", {"a": 10.0}, {"a": _snap(93.0)}, 10.0, 90.0, NOW_S
            )
            == "a"
        )

    def test_unknown_active_releases_only_above_the_floor(self):
        # With no active measurement the floor itself is the release bound
        state = self._state()
        assert (
            auto_rank.no_return_account(
                "proactive", state, "c", {"a": 10.0}, {"a": _snap(93.0)}, None, 90.0, NOW_S
            )
            == "a"  # exactly at the floor — not above it
        )
        assert (
            auto_rank.no_return_account(
                "proactive", state, "c", {"a": 11.0}, {"a": _snap(93.0)}, None, 90.0, NOW_S
            )
            is None
        )


class TestLeftAccountRecovered:
    def _state(self, **kw) -> AutoState:
        base = AutoState(
            last_switch_from="a", left_headroom=4.0, left_recovery_at_s=NOW_S + 100_000.0
        )
        return dataclasses.replace(base, **kw)

    def test_no_recorded_departure_is_not_recoverable(self):
        state = AutoState(last_switch_from="a")
        # No snapshot fields at all → only the landing floor can release
        assert not auto_rank.left_account_recovered(
            state, {"a": 4.0}, {"a": _snap(95.0)}, 90.0, NOW_S
        )

    def test_never_left_anything_releases(self):
        # No departure record → no evidence either way → release
        assert auto_rank.left_account_recovered(EMPTY_AUTO_STATE, {}, {}, 90.0, NOW_S)

    def test_landing_floor_releases(self):
        state = self._state()
        assert auto_rank.left_account_recovered(state, {"a": 15.0}, {"a": _snap(80.0)}, 90.0, NOW_S)

    def test_landing_floor_is_strict(self):
        # Exactly at 100 - threshold is still at the threshold — not released
        state = self._state(left_headroom=8.0)
        assert not auto_rank.left_account_recovered(
            state, {"a": 10.0}, {"a": _snap(90.0)}, 90.0, NOW_S
        )

    def test_floor_leg_runs_before_the_baseline(self):
        # left_headroom too high for the baseline leg (11 < 15+3) — only the
        # floor can release, so the floor expression itself is observable
        state = self._state(left_headroom=15.0)
        assert auto_rank.left_account_recovered(state, {"a": 11.0}, {"a": _snap(95.0)}, 90.0, NOW_S)

    def test_departure_baseline_plus_spent_releases(self):
        state = self._state()
        # 4 + 3 = 7 — a at exactly 7 crosses the baseline leg
        assert auto_rank.left_account_recovered(state, {"a": 7.0}, {"a": _snap(93.0)}, 90.0, NOW_S)

    def test_baseline_minus_epsilon_holds(self):
        state = self._state()
        assert not auto_rank.left_account_recovered(
            state, {"a": 6.9}, {"a": _snap(93.1)}, 90.0, NOW_S
        )

    def test_reset_leg_reached_when_headroom_legs_fail(self):
        # h=4: under the floor AND under the 4+3 baseline — only the improved
        # binding reset can release, so the hysteresis term is observable.
        # Improved by only 200s — under the 300s anti-flap margin.
        state = self._state()
        assert not auto_rank.left_account_recovered(
            state, {"a": 4.0}, {"a": _snap(96.0, NOW_S + 99_800.0)}, 90.0, NOW_S
        )

    def test_reset_improving_by_hysteresis_releases(self):
        state = self._state()
        # Departure reset was +100000s; now +50000s — improved > 300s
        assert auto_rank.left_account_recovered(
            state, {"a": 4.0}, {"a": _snap(96.0, NOW_S + 50_000.0)}, 90.0, NOW_S
        )


class TestChoose:
    """The no-return wrapper: barred ranking, released when it leaves nothing."""

    def test_barred_empty_ranking_retries_unbarred_when_recovered(self):
        state = AutoState(
            last_switch_at_s=NOW_S - 400.0,
            last_switch_from="a",
            last_switch_to="c",
            left_headroom=4.0,
            left_recovery_at_s=NOW_S + 100_000.0,
        )
        # "a" is the only candidate and it HAS recovered (30 > 4+3 baseline)
        ordered, any_known = auto_rank.choose(
            "proactive",
            candidates=["a"],
            snapshots={"a": _snap(50.0), "c": _snap(97.0)},
            headroom={"a": 30.0},
            active="c",
            active_headroom=3.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            state=state,
            now_s=NOW_S,
        )
        assert ordered == ["a"]
        assert any_known

    def test_unrecovered_barred_candidate_stays_barred(self):
        state = AutoState(
            last_switch_at_s=NOW_S - 400.0,
            last_switch_from="a",
            last_switch_to="c",
            left_headroom=4.0,
            left_recovery_at_s=NOW_S + 100_000.0,
        )
        ordered, _ = auto_rank.choose(
            "proactive",
            candidates=["a"],
            snapshots={"a": _snap(96.0), "c": _snap(97.0)},
            headroom={"a": 4.0},  # unchanged since departure — a flap
            active="c",
            active_headroom=3.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            state=state,
            now_s=NOW_S,
        )
        assert ordered == []

    def test_bar_holds_for_an_unrecovered_qualifying_candidate(self):
        # The observable case for the bar itself: a WOULD rank (all spent,
        # 8 pts vs the 4-pt floor ratio) but it is barred and unrecovered —
        # every argument to the barred check is load-bearing here
        state = AutoState(
            last_switch_at_s=NOW_S - 400.0,
            last_switch_from="a",
            last_switch_to="c",
            left_headroom=6.0,
            left_recovery_at_s=NOW_S + 50_000.0,
        )
        ordered, any_known = auto_rank.choose(
            "proactive",
            candidates=["a"],
            snapshots={"a": _snap(92.0, NOW_S + 80_000.0), "c": _snap(98.0, NOW_S + 200_000.0)},
            headroom={"a": 8.0, "c": 2.0},
            active="c",
            active_headroom=2.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            state=state,
            now_s=NOW_S,
        )
        assert ordered == []
        assert any_known

    def test_manual_move_releases_the_bar(self):
        # Engine landed on "c" but the user moved to "d" — the bar protects
        # nothing; the unbarred candidate ranks again
        state = AutoState(
            last_switch_at_s=NOW_S - 400.0,
            last_switch_from="a",
            last_switch_to="c",
            left_headroom=6.0,
            left_recovery_at_s=NOW_S + 50_000.0,
        )
        ordered, _ = auto_rank.choose(
            "proactive",
            candidates=["a"],
            snapshots={"a": _snap(92.0, NOW_S + 80_000.0), "d": _snap(98.0, NOW_S + 200_000.0)},
            headroom={"a": 8.0, "d": 2.0},
            active="d",
            active_headroom=2.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            state=state,
            now_s=NOW_S,
        )
        assert ordered == ["a"]

    def test_release_reranks_and_admits_on_the_fallback_axis(self):
        # Bar holds (5 < 2x3 dominance fails) but a IS recovered (reset
        # improved from +100000s to +50000s) — pass 1 empties on the bar,
        # pass 2 re-admits it
        state = AutoState(
            last_switch_at_s=NOW_S - 400.0,
            last_switch_from="a",
            last_switch_to="c",
            left_headroom=4.0,
            left_recovery_at_s=NOW_S + 100_000.0,
        )
        ordered, any_known = auto_rank.choose(
            "proactive",
            candidates=["a"],
            snapshots={"a": _snap(95.0, NOW_S + 50_000.0), "c": _snap(97.0, NOW_S + 60_000.0)},
            headroom={"a": 5.0, "c": 3.0},
            active="c",
            active_headroom=3.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            state=state,
            now_s=NOW_S,
        )
        assert ordered == ["a"]
        assert any_known

    def test_release_rerank_can_still_refuse(self):
        # Same release fires, but on the re-rank a's reset (50000s) is not
        # strictly 300s sooner than the active's (50300s) — nothing admits
        state = AutoState(
            last_switch_at_s=NOW_S - 400.0,
            last_switch_from="a",
            last_switch_to="c",
            left_headroom=4.0,
            left_recovery_at_s=NOW_S + 100_000.0,
        )
        ordered, _ = auto_rank.choose(
            "proactive",
            candidates=["a"],
            snapshots={"a": _snap(95.0, NOW_S + 50_000.0), "c": _snap(97.0, NOW_S + 50_300.0)},
            headroom={"a": 5.0, "c": 3.0},
            active="c",
            active_headroom=3.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            state=state,
            now_s=NOW_S,
        )
        assert ordered == []

    def test_release_rerank_on_the_healthy_path_still_applies_margins(self):
        # a recovered past the floor (15 pts) but cannot dominate the 8-pt
        # active (15 < 16) — bar holds through pass 1; the release fires and
        # the re-rank still refuses on hysteresis (15 - 8 = 7 < 10)
        state = AutoState(
            last_switch_at_s=NOW_S - 400.0,
            last_switch_from="a",
            last_switch_to="c",
            left_headroom=4.0,
            left_recovery_at_s=NOW_S + 100_000.0,
        )
        ordered, _ = auto_rank.choose(
            "proactive",
            candidates=["a"],
            snapshots={"a": _snap(85.0), "c": _snap(92.0)},
            headroom={"a": 15.0, "c": 8.0},
            active="c",
            active_headroom=8.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            state=state,
            now_s=NOW_S,
        )
        assert ordered == []

    def test_bar_released_by_dominance_under_all_spent(self):
        # All spent: a recovered to 9 pts (departure baseline 6+3) and beats
        # the 3-pt active by the 2x ratio — released upstream, then ranks
        state = AutoState(
            last_switch_at_s=NOW_S - 400.0,
            last_switch_from="a",
            last_switch_to="c",
            left_headroom=6.0,
            left_recovery_at_s=NOW_S + 100_000.0,
        )
        ordered, _ = auto_rank.choose(
            "proactive",
            candidates=["a"],
            snapshots={"a": _snap(91.0, NOW_S + 200_000.0), "c": _snap(97.0, NOW_S + 300_000.0)},
            headroom={"a": 9.0, "c": 3.0},
            active="c",
            active_headroom=3.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            state=state,
            now_s=NOW_S,
        )
        assert ordered == ["a"]

    def test_next_available_orders_the_first_pass(self):
        # No bar at all — plain registry rotation under healthy landings
        ordered, _ = auto_rank.choose(
            "proactive",
            candidates=["a", "b"],
            snapshots={"a": _snap(50.0), "b": _snap(40.0), "c": _snap(95.0)},
            headroom={"a": 30.0, "b": 60.0, "c": 5.0},
            active="c",
            active_headroom=5.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="next-available",
            state=EMPTY_AUTO_STATE,
            now_s=NOW_S,
        )
        assert ordered == ["a", "b"]

    def test_nonempty_ranking_never_reranks(self):
        # a is barred AND recovered (7 >= 4+3 baseline) but cannot dominate
        # (7 < 2x4). b already qualifies — a nonempty pass-1 must NOT
        # trigger the release re-rank that would re-admit a
        state = AutoState(
            last_switch_at_s=NOW_S - 400.0,
            last_switch_from="a",
            last_switch_to="c",
            left_headroom=4.0,
            left_recovery_at_s=NOW_S + 100_000.0,
        )
        ordered, _ = auto_rank.choose(
            "proactive",
            candidates=["a", "b"],
            snapshots={
                "a": _snap(93.0, NOW_S + 3600.0),
                "b": _snap(92.0, NOW_S + 25_000.0),
                "c": _snap(96.0, NOW_S + 20_000.0),
            },
            headroom={"a": 7.0, "b": 8.0, "c": 4.0},
            active="c",
            active_headroom=4.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            state=state,
            now_s=NOW_S,
        )
        assert ordered == ["b"]

    def test_active_recovery_time_is_part_of_the_census(self):
        # a's reset lands exactly 300s before the active's — the margin
        # refuses. Without the census (active unresolvable) a would admit
        # on the fallback/headroom axes instead
        ordered, _ = auto_rank.choose(
            "proactive",
            candidates=["a"],
            snapshots={"a": _snap(95.0, NOW_S + 3300.0), "c": _snap(95.0, NOW_S + 3600.0)},
            headroom={"a": 5.0, "c": 5.0},
            active="c",
            active_headroom=5.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            state=EMPTY_AUTO_STATE,
            now_s=NOW_S,
        )
        assert ordered == []

    def test_held_bar_still_yields_other_candidates(self):
        # a recovered past the floor (35 > 10) but cannot dominate the 20-pt
        # active (35 < 2x20) — the measured-active dominance leg is what
        # holds the bar. A None active would release on the floor alone.
        # With the bar holding and b in the list, the answer is b alone.
        state = AutoState(
            last_switch_at_s=NOW_S - 400.0,
            last_switch_from="a",
            last_switch_to="c",
            left_headroom=None,
            left_recovery_at_s=None,
        )
        ordered, _ = auto_rank.choose(
            "proactive",
            candidates=["a", "b"],
            snapshots={"a": _snap(65.0), "b": _snap(69.0), "c": _snap(80.0)},
            headroom={"a": 35.0, "b": 31.0, "c": 20.0},
            active="c",
            active_headroom=20.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            state=state,
            now_s=NOW_S,
        )
        assert ordered == ["b"]

    def test_active_headroom_feeds_the_all_spent_check(self):
        # active measured at 95% → all_above → a at the threshold qualifies
        # on the headroom axis (10 >= 5x2). Dropping the active measurement
        # flips to the healthy-landing path where a is refused outright
        ordered, _ = auto_rank.choose(
            "proactive",
            candidates=["a"],
            snapshots={"a": _snap(90.0, NOW_S + 200_000.0), "c": _snap(95.0, NOW_S + 300_000.0)},
            headroom={"a": 10.0, "c": 5.0},
            active="c",
            active_headroom=5.0,
            threshold=90.0,
            hysteresis_pct=10.0,
            strategy="best",
            state=EMPTY_AUTO_STATE,
            now_s=NOW_S,
        )
        assert ordered == ["a"]


class TestEarliestRecoveryEpoch:
    def test_min_over_exhausted_accounts_latest_reset(self):
        # a blocked on 5h (resets +1h) AND 7d (+2h) → usable at +2h;
        # c blocked on 5h only (+30m) → fleet earliest = +30m
        snaps = {
            "a": _snap(100.0, NOW_S + 3600.0, 100.0, NOW_S + 7200.0),
            "b": _snap(50.0, NOW_S + 3600.0),  # not exhausted — ignored
            "c": _snap(100.0, NOW_S + 1800.0),
        }
        assert auto_rank.earliest_recovery_epoch(snaps, NOW_S) == NOW_S + 1800.0

    def test_blocked_account_without_reset_is_unprovable(self):
        snaps = {"a": _snap(100.0, NOW_S + 3600.0), "b": _snap(100.0, None)}
        assert auto_rank.earliest_recovery_epoch(snaps, NOW_S) is None

    def test_past_reset_is_unprovable(self):
        snaps = {"a": _snap(100.0, NOW_S - 10.0)}
        assert auto_rank.earliest_recovery_epoch(snaps, NOW_S) is None

    def test_reset_exactly_at_now_is_unprovable(self):
        snaps = {"a": _snap(100.0, NOW_S)}
        assert auto_rank.earliest_recovery_epoch(snaps, NOW_S) is None

    def test_none_snapshot_does_not_stop_the_scan(self):
        snaps = {"x": None, "a": _snap(100.0, NOW_S + 3600.0)}
        assert auto_rank.earliest_recovery_epoch(snaps, NOW_S) == NOW_S + 3600.0

    def test_no_exhausted_account_is_none(self):
        snaps = {"a": _snap(50.0, NOW_S + 3600.0)}
        assert auto_rank.earliest_recovery_epoch(snaps, NOW_S) is None

    def test_no_snapshots_is_none(self):
        assert auto_rank.earliest_recovery_epoch({"a": None}, NOW_S) is None
