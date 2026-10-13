"""``poll_policy`` — due candidates and the overslept-plan branch.

The helpers the auto loop's scheduler runs each tick: which accounts are
due, and what a plan that overslept its interval does next.
"""

from support.poll_rigs import cache_entry as _entry

from claude_acc_manager.usage.domain.services import poll_policy


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
