"""``auto_rank.choose`` — the final pick over ranked candidates + guards."""

from support.rank_requests import NOW_S
from support.rank_requests import rank_request as _request
from support.rank_requests import snap as _snap

from claude_acc_manager.auto.domain.auto_state import EMPTY_AUTO_STATE, AutoState
from claude_acc_manager.auto.domain.services import auto_rank


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
            _request(
                trigger="proactive",
                candidates=["a"],
                snapshots={"a": _snap(50.0), "c": _snap(97.0)},
                headroom={"a": 30.0},
                active="c",
                active_headroom=3.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
            state=state,
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
            _request(
                trigger="proactive",
                candidates=["a"],
                snapshots={"a": _snap(96.0), "c": _snap(97.0)},
                headroom={"a": 4.0},
                active="c",
                active_headroom=3.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
            state=state,
        )  # unchanged since departure — a flap
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
            _request(
                trigger="proactive",
                candidates=["a"],
                snapshots={"a": _snap(92.0, NOW_S + 80_000.0), "c": _snap(98.0, NOW_S + 200_000.0)},
                headroom={"a": 8.0, "c": 2.0},
                active="c",
                active_headroom=2.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
            state=state,
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
            _request(
                trigger="proactive",
                candidates=["a"],
                snapshots={"a": _snap(92.0, NOW_S + 80_000.0), "d": _snap(98.0, NOW_S + 200_000.0)},
                headroom={"a": 8.0, "d": 2.0},
                active="d",
                active_headroom=2.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
            state=state,
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
            _request(
                trigger="proactive",
                candidates=["a"],
                snapshots={"a": _snap(95.0, NOW_S + 50_000.0), "c": _snap(97.0, NOW_S + 60_000.0)},
                headroom={"a": 5.0, "c": 3.0},
                active="c",
                active_headroom=3.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
            state=state,
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
            _request(
                trigger="proactive",
                candidates=["a"],
                snapshots={"a": _snap(95.0, NOW_S + 50_000.0), "c": _snap(97.0, NOW_S + 50_300.0)},
                headroom={"a": 5.0, "c": 3.0},
                active="c",
                active_headroom=3.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
            state=state,
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
            _request(
                trigger="proactive",
                candidates=["a"],
                snapshots={"a": _snap(85.0), "c": _snap(92.0)},
                headroom={"a": 15.0, "c": 8.0},
                active="c",
                active_headroom=8.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
            state=state,
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
            _request(
                trigger="proactive",
                candidates=["a"],
                snapshots={
                    "a": _snap(91.0, NOW_S + 200_000.0),
                    "c": _snap(97.0, NOW_S + 300_000.0),
                },
                headroom={"a": 9.0, "c": 3.0},
                active="c",
                active_headroom=3.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
            state=state,
        )
        assert ordered == ["a"]

    def test_next_available_orders_the_first_pass(self):
        # No bar at all — plain registry rotation under healthy landings
        ordered, _ = auto_rank.choose(
            _request(
                trigger="proactive",
                candidates=["a", "b"],
                snapshots={"a": _snap(50.0), "b": _snap(40.0), "c": _snap(95.0)},
                headroom={"a": 30.0, "b": 60.0, "c": 5.0},
                active="c",
                active_headroom=5.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="next-available",
                now_s=NOW_S,
            ),
            state=EMPTY_AUTO_STATE,
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
            _request(
                trigger="proactive",
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
                now_s=NOW_S,
            ),
            state=state,
        )
        assert ordered == ["b"]

    def test_active_recovery_time_is_part_of_the_census(self):
        # a's reset lands exactly 300s before the active's — the margin
        # refuses. Without the census (active unresolvable) a would admit
        # on the fallback/headroom axes instead
        ordered, _ = auto_rank.choose(
            _request(
                trigger="proactive",
                candidates=["a"],
                snapshots={"a": _snap(95.0, NOW_S + 3300.0), "c": _snap(95.0, NOW_S + 3600.0)},
                headroom={"a": 5.0, "c": 5.0},
                active="c",
                active_headroom=5.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
            state=EMPTY_AUTO_STATE,
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
            _request(
                trigger="proactive",
                candidates=["a", "b"],
                snapshots={"a": _snap(65.0), "b": _snap(69.0), "c": _snap(80.0)},
                headroom={"a": 35.0, "b": 31.0, "c": 20.0},
                active="c",
                active_headroom=20.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
            state=state,
        )
        assert ordered == ["b"]

    def test_active_headroom_feeds_the_all_spent_check(self):
        # active measured at 95% → all_above → a at the threshold qualifies
        # on the headroom axis (10 >= 5x2). Dropping the active measurement
        # flips to the healthy-landing path where a is refused outright
        ordered, _ = auto_rank.choose(
            _request(
                trigger="proactive",
                candidates=["a"],
                snapshots={
                    "a": _snap(90.0, NOW_S + 200_000.0),
                    "c": _snap(95.0, NOW_S + 300_000.0),
                },
                headroom={"a": 10.0, "c": 5.0},
                active="c",
                active_headroom=5.0,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
            state=EMPTY_AUTO_STATE,
        )
        assert ordered == ["a"]
