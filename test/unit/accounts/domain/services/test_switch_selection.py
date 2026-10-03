"""Unit tests for accounts.domain.services.switch_selection.

The selection contract pinned to a pure function: the caller resolves
names/anchors/eligibility sets and per-account headroom; the code under
test only decides.
"""

from claude_acc_manager.accounts.domain.services.switch_selection import (
    select_switch_target,
)


class TestRotation:
    """Bare switch walks registry order past the anchor, skipping ineligible."""

    def test_picks_the_next_account_after_the_anchor(self):
        # act / assert
        selection = select_switch_target(
            ("a", "b", "c"),
            anchor="a",
            current="a",
            strategy="rotation",
        )
        assert selection.target == "b"
        assert selection.outcome == "switch"

    def test_wraps_around_to_the_front(self):
        # act / assert
        selection = select_switch_target(
            ("a", "b", "c"), anchor="c", current="c", strategy="rotation"
        )
        assert selection.target == "a"

    def test_anchor_outside_the_registry_starts_after_the_first(self):
        # arrange — an unmanaged live login anchors nowhere; index falls back
        # to 0, so the first account is treated as the current one
        # act / assert
        selection = select_switch_target(
            ("a", "b", "c"), anchor=None, current=None, strategy="rotation"
        )
        assert selection.target == "b"

    def test_a_single_account_is_no_valid_target(self):
        # act / assert
        selection = select_switch_target(("a",), anchor="a", current="a", strategy="rotation")
        assert selection.target is None
        assert selection.outcome == "no-valid-target"

    def test_skips_disabled_quarantined_and_credentialless_with_notes(self):
        # act
        selection = select_switch_target(
            ("a", "b", "c", "d", "e"),
            anchor="a",
            current="a",
            strategy="rotation",
            disabled={"b"},
            quarantined={"c"},
            has_credentials={"a", "b", "c", "e"},
        )

        # assert — every skip is named, in walk order
        assert selection.target == "e"
        assert [(s.name, s.reason) for s in selection.skipped] == [
            ("b", "disabled"),
            ("c", "quarantined"),
            ("d", "no-credentials"),
        ]

    def test_all_ineligible_is_no_valid_target(self):
        # act / assert
        selection = select_switch_target(
            ("a", "b"), anchor="a", current="a", strategy="rotation", disabled={"b"}
        )
        assert selection.target is None
        assert selection.outcome == "no-valid-target"
        assert [(s.name, s.reason) for s in selection.skipped] == [("b", "disabled")]


class TestNextAvailable:
    """next-available is rotation plus an at-limit skip — unknown is not exhausted."""

    def test_skips_an_exhausted_account(self):
        # act
        selection = select_switch_target(
            ("a", "b", "c"),
            anchor="a",
            current="a",
            strategy="next-available",
            headroom={"b": 0.0, "c": 40.0},
        )

        # assert
        assert selection.target == "c"
        assert [(s.name, s.reason) for s in selection.skipped] == [("b", "at-limit")]

    def test_partial_headroom_is_not_at_limit(self):
        # arrange — 0.5% left is not exhausted; the bound is <= 0
        # act / assert
        selection = select_switch_target(
            ("a", "b"),
            anchor="a",
            current="a",
            strategy="next-available",
            headroom={"b": 0.5},
        )
        assert selection.target == "b"

    def test_unknown_usage_is_never_skipped(self):
        # arrange — b's usage simply isn't in the map
        # act / assert
        selection = select_switch_target(
            ("a", "b", "c"),
            anchor="a",
            current="a",
            strategy="next-available",
            headroom={"c": 10.0},
        )
        assert selection.target == "b"
        assert selection.skipped == ()

    def test_all_candidates_at_limit_is_candidates_exhausted(self):
        # act / assert
        selection = select_switch_target(
            ("a", "b", "c"),
            anchor="a",
            current="a",
            strategy="next-available",
            headroom={"b": 0.0, "c": -5.0},
        )
        assert selection.target is None
        assert selection.outcome == "candidates-exhausted"

    def test_exhausted_wins_over_other_skip_reasons(self):
        # arrange — one disabled AND one at-limit: the outcome names the limit
        # act / assert
        selection = select_switch_target(
            ("a", "b", "c"),
            anchor="a",
            current="a",
            strategy="next-available",
            disabled={"b"},
            headroom={"c": 0.0},
        )
        assert selection.outcome == "candidates-exhausted"
        assert [(s.name, s.reason) for s in selection.skipped] == [
            ("b", "disabled"),
            ("c", "at-limit"),
        ]

    def test_no_usage_skips_but_all_ineligible_is_no_valid_target(self):
        # act / assert
        selection = select_switch_target(
            ("a", "b"),
            anchor="a",
            current="a",
            strategy="next-available",
            quarantined={"b"},
        )
        assert selection.outcome == "no-valid-target"
        assert [(s.name, s.reason) for s in selection.skipped] == [("b", "quarantined")]


class TestBest:
    """best switches only onto provably-more-headroom accounts."""

    def test_switches_to_the_strictly_better_account(self):
        # act / assert
        selection = select_switch_target(
            ("a", "b", "c"),
            anchor="a",
            current="a",
            strategy="best",
            headroom={"a": 20.0, "b": 60.0, "c": 40.0},
        )
        assert selection.target == "b"
        assert selection.outcome == "switch"

    def test_equal_headroom_stays(self):
        # arrange — ties resolve in favour of staying put
        # act / assert
        selection = select_switch_target(
            ("a", "b"),
            anchor="a",
            current="a",
            strategy="best",
            headroom={"a": 50.0, "b": 50.0},
        )
        assert selection.target is None
        assert selection.outcome == "already-best"

    def test_candidate_ties_resolve_to_registry_order(self):
        # act / assert — first maximal element wins
        selection = select_switch_target(
            ("a", "b", "c"),
            anchor="a",
            current="a",
            strategy="best",
            headroom={"a": 10.0, "b": 80.0, "c": 80.0},
        )
        assert selection.target == "b"

    def test_current_unmeasurable_is_usage_unavailable(self):
        # arrange — no entry for "a": can't prove any target is better
        # act / assert
        selection = select_switch_target(
            ("a", "b"),
            anchor="a",
            current="a",
            strategy="best",
            headroom={"b": 99.0},
        )
        assert selection.target is None
        assert selection.outcome == "usage-unavailable"

    def test_no_live_current_is_usage_unavailable(self):
        # arrange — an unmanaged live login has no measured headroom
        # act / assert
        selection = select_switch_target(
            ("a", "b"),
            anchor="b",
            current=None,
            strategy="best",
            headroom={"a": 90.0, "b": 30.0},
        )
        assert selection.outcome == "usage-unavailable"

    def test_no_candidate_with_known_usage_is_usage_unavailable(self):
        # act / assert
        selection = select_switch_target(
            ("a", "b", "c"),
            anchor="a",
            current="a",
            strategy="best",
            headroom={"a": 50.0},
        )
        assert selection.outcome == "usage-unavailable"

    def test_incomplete_comparison_is_usage_unavailable(self):
        # arrange — current beats every MEASURED candidate, but "c" is
        # unknown: can't claim already-best or exhausted
        # act / assert
        selection = select_switch_target(
            ("a", "b", "c"),
            anchor="a",
            current="a",
            strategy="best",
            headroom={"a": 60.0, "b": 30.0},
        )
        assert selection.outcome == "usage-unavailable"

    def test_all_known_and_everything_at_limit_is_candidates_exhausted(self):
        # act / assert
        selection = select_switch_target(
            ("a", "b"),
            anchor="a",
            current="a",
            strategy="best",
            headroom={"a": 0.0, "b": 0.0},
        )
        assert selection.outcome == "candidates-exhausted"

    def test_positive_sub_percent_current_is_already_best(self):
        # arrange — 0.5% left beats a measured peer at 0.3%; the bound is <= 0
        # act / assert
        selection = select_switch_target(
            ("a", "b"),
            anchor="a",
            current="a",
            strategy="best",
            headroom={"a": 0.5, "b": 0.3},
        )
        assert selection.outcome == "already-best"

    def test_everything_measured_and_current_wins_is_already_best(self):
        # act / assert
        selection = select_switch_target(
            ("a", "b"),
            anchor="a",
            current="a",
            strategy="best",
            headroom={"a": 40.0, "b": 30.0},
        )
        assert selection.outcome == "already-best"

    def test_ineligible_accounts_are_not_candidates(self):
        # arrange — the only better account is quarantined
        # act
        selection = select_switch_target(
            ("a", "b"),
            anchor="a",
            current="a",
            strategy="best",
            quarantined={"b"},
            headroom={"a": 10.0, "b": 90.0},
        )

        # assert — the stay is named and every ineligible peer is listed
        assert selection.target is None
        assert selection.outcome == "no-valid-target"
        assert [(s.name, s.reason) for s in selection.skipped] == [("b", "quarantined")]

    def test_disabled_and_credentialless_are_not_candidates(self):
        # arrange — two candidates, each ineligible for a different reason
        # act
        selection = select_switch_target(
            ("a", "b", "c"),
            anchor="a",
            current="a",
            strategy="best",
            disabled={"b"},
            has_credentials={"a", "b"},
            headroom={"a": 10.0, "b": 90.0, "c": 90.0},
        )

        # assert
        assert selection.outcome == "no-valid-target"
        assert [(s.name, s.reason) for s in selection.skipped] == [
            ("b", "disabled"),
            ("c", "no-credentials"),
        ]
