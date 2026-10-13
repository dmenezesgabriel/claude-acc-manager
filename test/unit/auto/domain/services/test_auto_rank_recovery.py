"""``auto_rank`` — the recovery axis and earliest-recovery epochs."""

from support.rank_requests import NOW_S
from support.rank_requests import rank_request as _request
from support.rank_requests import snap as _snap

from claude_acc_manager.auto.domain.services import auto_rank


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
            _request(
                trigger="proactive",
                candidates=["a", "b"],
                snapshots=self._snapshots(),
                headroom={"a": 5.0, "b": 4.0},
                active="c",
                active_headroom=3.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
            no_return=None,
        )
        assert ordered == ["a", "b"]
        assert any_known

    def test_recovery_axis_needs_the_hysteresis_margin(self):
        # a returns only 100s sooner than the active — under 300s hysteresis
        snapshots = {"a": _snap(95.0, NOW_S + 3500.0), "c": _snap(97.0, NOW_S + 3600.0)}
        ordered, _ = auto_rank.rank_candidates(
            _request(
                trigger="proactive",
                candidates=["a"],
                snapshots=snapshots,
                headroom={"a": 5.0},
                active="c",
                active_headroom=3.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
            no_return=None,
        )
        assert ordered == []

    def test_recovery_axis_margin_is_strictly_before(self):
        # a returns exactly 300s sooner than the active — on the boundary,
        # the hysteresis refuses the move
        snapshots = {"a": _snap(95.0, NOW_S + 3300.0), "c": _snap(97.0, NOW_S + 3600.0)}
        ordered, _ = auto_rank.rank_candidates(
            _request(
                trigger="proactive",
                candidates=["a"],
                snapshots=snapshots,
                headroom={"a": 5.0},
                active="c",
                active_headroom=3.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
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
            _request(
                trigger="proactive",
                candidates=["a", "b"],
                snapshots=snapshots,
                headroom={"a": 5.0, "b": 2.0},
                active="c",
                active_headroom=2.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
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
            _request(
                trigger="proactive",
                candidates=["a", "b"],
                snapshots=snapshots,
                headroom={"a": 5.0, "b": 8.0},
                active="c",
                active_headroom=3.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
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
            _request(
                trigger="proactive",
                candidates=["a", "b"],
                snapshots=snapshots,
                headroom={"a": 5.0, "b": 10.0},
                active="c",
                active_headroom=5.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
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
            _request(
                trigger="proactive",
                candidates=["a", "b"],
                snapshots=snapshots,
                headroom={"a": 8.0, "b": 5.0},
                active="c",
                active_headroom=2.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
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
            _request(
                trigger="proactive",
                candidates=["a"],
                snapshots=snapshots,
                headroom={"a": 10.0},
                active="c",
                active_headroom=5.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
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
            _request(
                trigger="proactive",
                candidates=["a", "b"],
                snapshots=snapshots,
                headroom={"a": 1.0, "b": 5.0},
                active="c",
                active_headroom=0.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
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
            _request(
                trigger="proactive",
                candidates=["a"],
                snapshots=snapshots,
                headroom={"a": 3.0},
                active="c",
                active_headroom=5.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
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
            _request(
                trigger="proactive",
                candidates=["a"],
                snapshots=snapshots,
                headroom={"a": 8.0},
                active="c",
                active_headroom=3.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
            no_return=None,
        )  # 8 >= 3x2=6 — dominates on headroom
        assert ordered == ["a"]

    def test_far_out_peer_below_the_ratio_is_refused(self):
        snapshots = {
            "a": _snap(96.0, NOW_S + 200_000.0),
            "c": _snap(95.0, NOW_S + 300_000.0),
        }
        ordered, _ = auto_rank.rank_candidates(
            _request(
                trigger="proactive",
                candidates=["a"],
                snapshots=snapshots,
                headroom={"a": 4.0},
                active="c",
                active_headroom=5.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
            no_return=None,
        )  # 4 < 5x2=10 — not enough to move for
        assert ordered == []


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
