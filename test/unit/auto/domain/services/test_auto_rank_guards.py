"""``auto_rank`` — the no-return guards: spent fallback, no-return, left-account.

Before a candidate is chosen the domain checks whether the move can be
undone and whether the account we would leave recovers on its own.
"""

import dataclasses

from support.rank_requests import NOW_S
from support.rank_requests import rank_request as _request
from support.rank_requests import snap as _snap

from claude_acc_manager.auto.domain.auto_state import EMPTY_AUTO_STATE, AutoState
from claude_acc_manager.auto.domain.services import auto_rank


class TestSpentFallback:
    """Margin failures under all_above — re-admitted only when both sides
    are spent and the candidate's reset lands strictly sooner."""

    def _rank(self, candidates, snapshots, headroom, active_headroom=3.0):
        return auto_rank.rank_candidates(
            _request(
                trigger="proactive",
                candidates=candidates,
                snapshots=snapshots,
                headroom=headroom,
                active="c",
                active_headroom=active_headroom,
                threshold=90.0,
                hysteresis_pct=10.0,
                strategy="best",
                now_s=NOW_S,
            ),
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
            _request(
                trigger="proactive",
                active="c",
                headroom={"a": 4.0},
                snapshots={"a": _snap(95.0)},
                active_headroom=3.0,
                threshold=90.0,
                now_s=NOW_S,
            ),
            state=state,
        )
        assert barred == "a"

    def test_at_limit_never_bars(self):
        state = self._state()
        assert (
            auto_rank.no_return_account(
                _request(
                    trigger="at-limit",
                    active="c",
                    headroom={"a": 4.0},
                    snapshots={"a": _snap(95.0)},
                    active_headroom=0.0,
                    threshold=90.0,
                    now_s=NOW_S,
                ),
                state=state,
            )
            is None
        )

    def test_below_trigger_never_bars(self):
        state = self._state()
        assert (
            auto_rank.no_return_account(
                _request(
                    trigger="below",
                    active="c",
                    headroom={"a": 4.0},
                    snapshots={"a": _snap(95.0)},
                    active_headroom=30.0,
                    threshold=90.0,
                    now_s=NOW_S,
                ),
                state=state,
            )
            is None
        )

    def test_no_departure_record_means_no_bar(self):
        assert (
            auto_rank.no_return_account(
                _request(
                    trigger="proactive",
                    active="c",
                    headroom={},
                    snapshots={},
                    active_headroom=3.0,
                    threshold=90.0,
                    now_s=NOW_S,
                ),
                state=EMPTY_AUTO_STATE,
            )
            is None
        )

    def test_manual_move_off_the_landing_releases_the_bar(self):
        # Engine put us on "c"; user moved to "d" — the move is already undone
        state = self._state()
        assert (
            auto_rank.no_return_account(
                _request(
                    trigger="proactive",
                    active="d",
                    headroom={"a": 4.0},
                    snapshots={"a": _snap(95.0)},
                    active_headroom=3.0,
                    threshold=90.0,
                    now_s=NOW_S,
                ),
                state=state,
            )
            is None
        )

    def test_recovered_peer_is_released(self):
        # Left at 4 pts; now at 30 — beat the departure baseline + SPENT
        state = self._state()
        assert (
            auto_rank.no_return_account(
                _request(
                    trigger="proactive",
                    active="c",
                    headroom={"a": 30.0},
                    snapshots={"a": _snap(50.0, NOW_S + 3600.0)},
                    active_headroom=3.0,
                    threshold=90.0,
                    now_s=NOW_S,
                ),
                state=state,
            )
            is None
        )

    def test_recovered_peer_beating_the_ratio_is_released(self):
        # Recovery leg fires (reset improved by >300s), then the peer at 8
        # pts beats the burned-down active (1.5) by the 2x ratio → release
        state = self._state(left_headroom=6.0, left_recovery_at_s=NOW_S + 200_000.0)
        assert (
            auto_rank.no_return_account(
                _request(
                    trigger="proactive",
                    active="c",
                    headroom={"a": 8.0},
                    snapshots={"a": _snap(92.0, NOW_S + 100_000.0)},
                    active_headroom=1.5,
                    threshold=90.0,
                    now_s=NOW_S,
                ),
                state=state,
            )
            is None
        )

    def test_recovered_but_unmeasured_peer_stays_barred(self):
        # Recovery proven only by the reset leg; with no current headroom the
        # dominance check cannot run — no release
        state = self._state()
        assert (
            auto_rank.no_return_account(
                _request(
                    trigger="proactive",
                    active="c",
                    headroom={},
                    snapshots={"a": _snap(95.0, NOW_S + 50_000.0)},
                    active_headroom=3.0,
                    threshold=90.0,
                    now_s=NOW_S,
                ),
                state=state,
            )
            == "a"
        )

    def test_peer_exactly_at_the_ratio_releases(self):
        # left 10 pts vs active 5 — exactly 2x — meets the release bound
        state = self._state()
        assert (
            auto_rank.no_return_account(
                _request(
                    trigger="proactive",
                    active="c",
                    headroom={"a": 10.0},
                    snapshots={"a": _snap(93.0)},
                    active_headroom=5.0,
                    threshold=90.0,
                    now_s=NOW_S,
                ),
                state=state,
            )
            is None
        )

    def test_peer_under_the_ratio_stays_barred(self):
        # left 10 pts vs active 10 — recovered, but 10 < 2x10 — not better outright
        state = self._state()
        assert (
            auto_rank.no_return_account(
                _request(
                    trigger="proactive",
                    active="c",
                    headroom={"a": 10.0},
                    snapshots={"a": _snap(93.0)},
                    active_headroom=10.0,
                    threshold=90.0,
                    now_s=NOW_S,
                ),
                state=state,
            )
            == "a"
        )

    def test_unknown_active_releases_only_above_the_floor(self):
        # With no active measurement the floor itself is the release bound
        state = self._state()
        assert (
            auto_rank.no_return_account(
                _request(
                    trigger="proactive",
                    active="c",
                    headroom={"a": 10.0},
                    snapshots={"a": _snap(93.0)},
                    active_headroom=None,
                    threshold=90.0,
                    now_s=NOW_S,
                ),
                state=state,
            )
            == "a"  # exactly at the floor — not above it
        )
        assert (
            auto_rank.no_return_account(
                _request(
                    trigger="proactive",
                    active="c",
                    headroom={"a": 11.0},
                    snapshots={"a": _snap(93.0)},
                    active_headroom=None,
                    threshold=90.0,
                    now_s=NOW_S,
                ),
                state=state,
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
