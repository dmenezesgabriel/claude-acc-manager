"""``auto_rank.rank_candidates`` — ordering the eligible fleet."""

from support.rank_requests import NOW_S
from support.rank_requests import rank_request as _request
from support.rank_requests import snap as _snap

from claude_acc_manager.auto.domain.services import auto_rank


class TestRankCandidates:
    """Proactive ranking on the headroom axis (the ordinary case)."""

    def _snapshots(self):
        return {"a": _snap(50.0), "b": _snap(50.0), "c": _snap(50.0)}

    def test_best_picks_highest_headroom(self):
        ordered, any_known = auto_rank.rank_candidates(
            _request(
                trigger="proactive",
                candidates=["a", "b"],
                snapshots=self._snapshots(),
                headroom={"a": 30.0, "b": 60.0},
                active="c",
                active_headroom=5.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
            no_return=None,
        )
        assert ordered == ["b", "a"]
        assert any_known

    def test_best_requires_the_hysteresis_margin(self):
        # active 5 pts; a at 12 (7 over — under 10) is refused; b at 20 qualifies
        ordered, _ = auto_rank.rank_candidates(
            _request(
                trigger="proactive",
                candidates=["a", "b"],
                snapshots=self._snapshots(),
                headroom={"a": 12.0, "b": 20.0},
                active="c",
                active_headroom=5.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
            no_return=None,
        )
        assert ordered == ["b"]

    def test_candidate_at_threshold_cannot_be_a_proactive_landing(self):
        # b at 92% (8 pts) — healthy peers only; a at 40 pts qualifies
        ordered, _ = auto_rank.rank_candidates(
            _request(
                trigger="proactive",
                candidates=["a", "b"],
                snapshots=self._snapshots(),
                headroom={"a": 40.0, "b": 8.0},
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

    def test_unknown_and_exhausted_candidates_are_skipped(self):
        ordered, any_known = auto_rank.rank_candidates(
            _request(
                trigger="proactive",
                candidates=["a", "b", "c"],
                snapshots=self._snapshots(),
                headroom={"a": 30.0, "b": 0.0},
                active="d",
                active_headroom=5.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
            no_return=None,
        )  # c unmeasured
        assert ordered == ["a"]
        assert any_known

    def test_unmeasured_first_candidate_does_not_stop_the_scan(self):
        # the unknown entry must be skipped, not terminate the loop
        ordered, any_known = auto_rank.rank_candidates(
            _request(
                trigger="proactive",
                candidates=["u", "a"],
                snapshots=self._snapshots(),
                headroom={"a": 50.0},
                active="c",
                active_headroom=5.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
            no_return=None,
        )  # u unmeasured
        assert ordered == ["a"]
        assert any_known

    def test_equal_keys_keep_registry_order(self):
        # a key-tie must not re-sort by name — registry order wins
        ordered, _ = auto_rank.rank_candidates(
            _request(
                trigger="proactive",
                candidates=["z", "a"],
                snapshots=self._snapshots(),
                headroom={"a": 50.0, "z": 50.0},
                active="c",
                active_headroom=5.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
            no_return=None,
        )
        assert ordered == ["z", "a"]

    def test_nothing_known_reports_any_known_false(self):
        ordered, any_known = auto_rank.rank_candidates(
            _request(
                trigger="proactive",
                candidates=["a", "b"],
                snapshots=self._snapshots(),
                headroom={},
                active="d",
                active_headroom=5.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
            no_return=None,
        )
        assert ordered == []
        assert any_known is False

    def test_no_return_bars_the_account_we_left(self):
        ordered, _ = auto_rank.rank_candidates(
            _request(
                trigger="proactive",
                candidates=["a", "b"],
                snapshots=self._snapshots(),
                headroom={"a": 60.0, "b": 30.0},
                active="c",
                active_headroom=5.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
            no_return="a",
        )
        assert ordered == ["b"]

    def test_next_available_keeps_registry_order(self):
        ordered, _ = auto_rank.rank_candidates(
            _request(
                trigger="proactive",
                candidates=["a", "b"],
                snapshots=self._snapshots(),
                headroom={"a": 30.0, "b": 60.0},
                active="c",
                active_headroom=5.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="next-available",
                now_s=NOW_S,
            ),
            no_return=None,
        )
        # rotation semantics: first eligible, not highest headroom
        assert ordered == ["a", "b"]

    def test_at_limit_skips_the_hysteresis_margin(self):
        ordered, _ = auto_rank.rank_candidates(
            _request(
                trigger="at-limit",
                candidates=["a"],
                snapshots=self._snapshots(),
                headroom={"a": 1.0},
                active="c",
                active_headroom=0.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
            no_return="a",
        )  # the escape also ignores the no-return bar
        assert ordered == ["a"]

    def test_at_limit_still_refuses_zero_headroom(self):
        # escape or not, a fully dead account cannot take the session
        ordered, _ = auto_rank.rank_candidates(
            _request(
                trigger="at-limit",
                candidates=["a"],
                snapshots=self._snapshots(),
                headroom={"a": 0.0},
                active="c",
                active_headroom=0.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
            no_return=None,
        )
        assert ordered == []

    def test_at_limit_next_available_keeps_registry_order(self):
        ordered, _ = auto_rank.rank_candidates(
            _request(
                trigger="at-limit",
                candidates=["a", "b"],
                snapshots=self._snapshots(),
                headroom={"a": 10.0, "b": 50.0},
                active="c",
                active_headroom=0.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="next-available",
                now_s=NOW_S,
            ),
            no_return=None,
        )
        # rotation order wins even though b has more headroom
        assert ordered == ["a", "b"]

    def test_below_trigger_admits_without_margins(self):
        ordered, _ = auto_rank.rank_candidates(
            _request(
                trigger="below",
                candidates=["a"],
                snapshots=self._snapshots(),
                headroom={"a": 2.0},
                active="c",
                active_headroom=50.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
            no_return=None,
        )
        assert ordered == ["a"]

    def test_landing_one_point_below_threshold_is_admitted(self):
        # 89% utilized — just under the landing ceiling. active_headroom is
        # None: any measured-but-healthy active would make the margin fail
        # anyway, so the landing check is only distinguishable unmeasured
        ordered, _ = auto_rank.rank_candidates(
            _request(
                trigger="proactive",
                candidates=["a"],
                snapshots=self._snapshots(),
                headroom={"a": 11.0},
                active="c",
                active_headroom=None,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
            no_return=None,
        )
        assert ordered == ["a"]

    def test_landing_exactly_at_threshold_is_refused(self):
        ordered, _ = auto_rank.rank_candidates(
            _request(
                trigger="proactive",
                candidates=["a"],
                snapshots=self._snapshots(),
                headroom={"a": 10.0},
                active="c",
                active_headroom=None,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
            no_return=None,
        )
        assert ordered == []

    def test_margin_exactly_at_hysteresis_admits(self):
        # h - active == hysteresis_pct meets the margin — it is exclusive
        ordered, _ = auto_rank.rank_candidates(
            _request(
                trigger="proactive",
                candidates=["a"],
                snapshots=self._snapshots(),
                headroom={"a": 15.0},
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

    def test_margin_just_under_hysteresis_refuses(self):
        ordered, _ = auto_rank.rank_candidates(
            _request(
                trigger="proactive",
                candidates=["a"],
                snapshots=self._snapshots(),
                headroom={"a": 14.0},
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

    def test_unknown_active_headroom_skips_the_margin(self):
        # active_headroom=None → no margin comparison — admission by landing only
        ordered, _ = auto_rank.rank_candidates(
            _request(
                trigger="proactive",
                candidates=["a"],
                snapshots=self._snapshots(),
                headroom={"a": 12.0},
                active="c",
                active_headroom=None,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
            no_return=None,
        )
        assert ordered == ["a"]

    def test_margin_not_applied_under_next_available(self):
        # rotation does not demand a headroom margin
        ordered, _ = auto_rank.rank_candidates(
            _request(
                trigger="proactive",
                candidates=["a"],
                snapshots=self._snapshots(),
                headroom={"a": 12.0},
                active="c",
                active_headroom=5.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="next-available",
                now_s=NOW_S,
            ),
            no_return=None,
        )
        assert ordered == ["a"]
