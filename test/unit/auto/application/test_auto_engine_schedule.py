"""``AutoEngine.tick`` — scheduled collection and stale-candidate plans.

How the engine collects fresh usage for the fleet and re-plans when the
candidate it chose goes stale mid-tick.
"""

from support.engine_harness import NOW_S
from support.engine_harness import EngineHarness as _Harness
from support.engine_harness import account as _account
from support.engine_harness import entry as _entry
from support.engine_harness import identity as _identity
from support.engine_harness import report as _report
from support.engine_harness import snap as _snap

from claude_acc_manager.auto.domain.auto_event import (
    PollEvent,
    TickOutcome,
)
from claude_acc_manager.usage.domain.usage_cache_entry import UsageCacheEntry


class TestScheduledCollection:
    def test_due_active_and_one_due_candidate_are_fetched(self):
        # b and c both due → only the stalest (b, never fetched) goes
        h = _Harness(
            accounts=[_account("a"), _account("b"), _account("c")],
            credentialed={"b", "c"},
            identity=_identity("a"),
            cache_rows={
                "a": _entry(_snap(50.0), next_poll_at_s=NOW_S - 10.0),
                "b": _entry(None, fetched_at_s=None),
                "c": _entry(_snap(60.0), next_poll_at_s=NOW_S - 5.0),
            },
            reports={"a": _report(_snap(50.0)), "b": _report(_snap(60.0))},
        )
        outcome = h.tick()
        assert outcome == TickOutcome.NO_ACTION
        assert set(h.fetch.calls) == {
            ("a", True, True, 90.0),
            ("b", False, True, 90.0),
        }

    def test_fresh_active_is_not_refetched(self):
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={
                "a": _entry(_snap(50.0), next_poll_at_s=NOW_S + 300.0, poll_interval_s=300.0),
                "b": _entry(_snap(60.0), next_poll_at_s=NOW_S + 300.0),
            },
        )
        outcome = h.tick()
        assert outcome == TickOutcome.NO_ACTION
        assert h.fetch.calls == []

    def test_poll_event_reports_why_usage_stayed_unknown(self):
        # b is due but its fetch fails — the census names the last error.
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(95.0)), "b": _entry(None, fetched_at_s=None)},
            reports={
                "a": _report(_snap(95.0)),
                "b": _report(None, last_error="boom"),
            },
        )
        h.tick()
        poll = h.events[0]
        assert isinstance(poll, PollEvent)
        assert poll.fetch_errors == {"b": "boom"}

    def test_lone_active_below_band_fetches_nothing(self):
        # No candidates means no escalation — an empty fleet must not spend
        # a request on the active either.
        h = _Harness(
            accounts=[_account("a")],
            credentialed={"a"},
            identity=_identity("a"),
            cache_rows={
                "a": _entry(_snap(95.0), next_poll_at_s=NOW_S + 300.0, poll_interval_s=300.0)
            },
        )
        outcome = h.tick()
        assert outcome == TickOutcome.BLOCKED
        assert h.fetch.calls == []

    def test_unknown_active_escalates_to_the_fleet(self):
        # An unmeasurable active is the strongest reason to re-measure a
        # parked candidate: escalation fires on unknown headroom too.
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={
                "a": _entry(None),
                "b": _entry(_snap(60.0), next_poll_at_s=NOW_S + 300.0),
            },
            reports={"a": _report(None), "b": _report(_snap(60.0))},
        )
        h.tick()
        fetched = {name for name, *_ in h.fetch.calls}
        assert fetched == {"a", "b"}
        poll = h.events[0]
        assert isinstance(poll, PollEvent)
        # A failed fetch with no recorded cause stays out of fetch_errors —
        # the map names *why* usage is unknown, it never invents a reason.
        assert poll.fetch_errors == {}

    def test_fetch_error_falls_back_to_the_cached_cause(self):
        # b's fresh fetch reports no cause, but its cache row holds the last
        # observed error — that stored cause still names the unknown.
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={
                "a": _entry(_snap(50.0)),
                "b": UsageCacheEntry(
                    last_good=None,
                    fetched_at_s=NOW_S - 400.0,
                    consecutive_failures=1,
                    last_error="429",
                    backoff_until_s=None,
                    last_429_at_s=None,
                    next_poll_at_s=NOW_S - 1.0,
                    poll_interval_s=300.0,
                ),
            },
            reports={"a": _report(_snap(50.0)), "b": _report(None)},
        )
        h.tick()
        poll = h.events[0]
        assert isinstance(poll, PollEvent)
        assert poll.fetch_errors == {"b": "429"}

    def test_escalation_band_edge_is_inclusive(self):
        # utilization exactly at threshold - ESCALATION_MARGIN escalates
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={
                "a": _entry(_snap(75.0)),
                "b": _entry(_snap(60.0), next_poll_at_s=NOW_S + 300.0),
            },
            reports={"a": _report(_snap(75.0)), "b": _report(_snap(60.0))},
        )
        h.tick()
        fetched = {name for name, *_ in h.fetch.calls}
        assert fetched == {"a", "b"}

    def test_escalation_just_outside_the_band_skips_candidates(self):
        # 74% is one point outside threshold - margin → no fleet refetch
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={
                "a": _entry(_snap(74.0)),
                "b": _entry(_snap(60.0), next_poll_at_s=NOW_S + 300.0),
            },
            reports={"a": _report(_snap(74.0)), "b": _report(_snap(60.0))},
        )
        h.tick()
        fetched = {name for name, *_ in h.fetch.calls}
        assert fetched == {"a"}

    def test_escalation_fetches_everyone_inside_the_band(self):
        # active at 80% with threshold 90 → inside the 15pt escalation band
        h = _Harness(
            accounts=[_account("a"), _account("b"), _account("c")],
            credentialed={"b", "c"},
            identity=_identity("a"),
            cache_rows={
                "a": _entry(_snap(80.0), next_poll_at_s=NOW_S + 300.0),
                "b": _entry(_snap(60.0), next_poll_at_s=NOW_S + 300.0),
                "c": _entry(_snap(60.0), next_poll_at_s=NOW_S + 300.0),
            },
            reports={n: _report(_snap(80.0)) for n in ("a", "b", "c")},
        )
        h.tick()
        assert h.fetch.calls == [
            ("a", True, True, 90.0),
            ("b", False, True, 90.0),
            ("c", False, True, 90.0),
        ]

    def test_escalation_skips_serve_fresh_rows(self):
        # Regression: while the active sat in the band, the unconditional
        # force-fetch burned ~60 req/hr/identity against the ~30/hr budget
        # and self-induced the 429 freezes that left decisions on stale
        # last_good. A row younger than SERVE_TTL_S is already
        # decision-grade — b (60s old) is skipped, c (400s old) is not.
        h = _Harness(
            accounts=[_account("a"), _account("b"), _account("c")],
            credentialed={"b", "c"},
            identity=_identity("a"),
            cache_rows={
                "a": _entry(_snap(80.0), next_poll_at_s=NOW_S + 300.0),
                "b": _entry(_snap(60.0), fetched_at_s=NOW_S - 60.0, next_poll_at_s=NOW_S + 300.0),
                "c": _entry(_snap(60.0), next_poll_at_s=NOW_S + 300.0),
            },
            reports={"a": _report(_snap(80.0)), "c": _report(_snap(60.0))},
        )
        h.tick()
        fetched = {name for name, *_ in h.fetch.calls}
        assert fetched == {"a", "c"}

    def test_escalation_skips_reset_parked_exhausted(self):
        # b is exhausted with a deliberately wide plan — escalation must not
        # spend a request on it
        h = _Harness(
            accounts=[_account("a"), _account("b"), _account("c")],
            credentialed={"b", "c"},
            identity=_identity("a"),
            cache_rows={
                "a": _entry(_snap(80.0), next_poll_at_s=NOW_S + 300.0),
                "b": _entry(
                    _snap(100.0, NOW_S + 5000.0),
                    next_poll_at_s=NOW_S + 5000.0,
                    poll_interval_s=7200.0,
                ),
                "c": _entry(_snap(60.0), next_poll_at_s=NOW_S + 300.0),
            },
            reports={n: _report(_snap(80.0)) for n in ("a", "c")},
        )
        outcome = h.tick()
        # The parked row is skipped, not crashed on — the tick still lands
        # on the below-threshold no-action.
        assert outcome == TickOutcome.NO_ACTION
        fetched = {name for name, *_ in h.fetch.calls}
        assert fetched == {"a", "c"}

    def test_escalation_fetches_exhausted_on_moderate_interval(self):
        # b is exhausted but on an ordinary 300s plan — that is not a
        # reset-park, so escalation re-measures it.
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={
                "a": _entry(_snap(80.0), next_poll_at_s=NOW_S + 300.0),
                "b": _entry(_snap(100.0), next_poll_at_s=NOW_S + 700.0, poll_interval_s=300.0),
            },
            reports={"a": _report(_snap(80.0)), "b": _report(_snap(100.0))},
        )
        h.tick()
        fetched = {name for name, *_ in h.fetch.calls}
        assert fetched == {"a", "b"}

    def test_escalation_fetches_park_at_interval_floor(self):
        # interval exactly EXHAUSTED_INTERVAL_S is not "deliberately wide" —
        # the park needs a strictly wider plan.
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={
                "a": _entry(_snap(80.0), next_poll_at_s=NOW_S + 300.0),
                "b": _entry(_snap(100.0), next_poll_at_s=NOW_S + 700.0, poll_interval_s=600.0),
            },
            reports={"a": _report(_snap(80.0)), "b": _report(_snap(100.0))},
        )
        h.tick()
        fetched = {name for name, *_ in h.fetch.calls}
        assert fetched == {"a", "b"}

    def test_escalation_fetches_park_at_deadline(self):
        # next_poll_at exactly now means the park's deadline already passed —
        # no parking. The backoff keeps due_candidate from grabbing it first,
        # isolating the reset-parked check inside the escalation sweep.
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={
                "a": _entry(_snap(80.0), next_poll_at_s=NOW_S + 300.0),
                "b": UsageCacheEntry(
                    last_good=_snap(100.0),
                    fetched_at_s=NOW_S - 400.0,
                    consecutive_failures=0,
                    last_error=None,
                    backoff_until_s=NOW_S + 100.0,
                    last_429_at_s=None,
                    next_poll_at_s=NOW_S,
                    poll_interval_s=7200.0,
                ),
            },
            reports={"a": _report(_snap(80.0)), "b": _report(_snap(100.0))},
        )
        h.tick()
        fetched = {name for name, *_ in h.fetch.calls}
        assert fetched == {"a", "b"}

    def test_escalation_fetches_thin_headroom(self):
        # h = 0.5 is positive — not "at the limit" — so the wide plan is not
        # a park and escalation re-measures.
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={
                "a": _entry(_snap(80.0), next_poll_at_s=NOW_S + 300.0),
                "b": _entry(_snap(99.5), next_poll_at_s=NOW_S + 700.0, poll_interval_s=7200.0),
            },
            reports={"a": _report(_snap(80.0)), "b": _report(_snap(99.5))},
        )
        h.tick()
        fetched = {name for name, *_ in h.fetch.calls}
        assert fetched == {"a", "b"}


class TestStaleCandidatePlan:
    """The active's own row can carry a candidate-style slow plan — a parked
    credential that was measured as a candidate, then became live without a
    tightened plan. Age + a wide interval + sub-limit usage refetches it."""

    def test_stale_plan_fetches_the_active(self):
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={
                "a": _entry(
                    _snap(50.0),
                    fetched_at_s=NOW_S - 400.0,
                    next_poll_at_s=NOW_S + 800.0,
                    poll_interval_s=700.0,
                ),
                "b": _entry(_snap(60.0), next_poll_at_s=NOW_S + 300.0),
            },
            reports={"a": _report(_snap(50.0))},
        )
        h.tick()
        fetched = {name for name, *_ in h.fetch.calls}
        assert fetched == {"a"}

    def test_stale_plan_at_age_boundary_fetches(self):
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={
                "a": _entry(
                    _snap(50.0),
                    fetched_at_s=NOW_S - 300.0,
                    next_poll_at_s=NOW_S + 800.0,
                    poll_interval_s=700.0,
                ),
                "b": _entry(_snap(60.0), next_poll_at_s=NOW_S + 300.0),
            },
            reports={"a": _report(_snap(50.0))},
        )
        h.tick()
        fetched = {name for name, *_ in h.fetch.calls}
        assert fetched == {"a"}

    def test_recently_fetched_active_is_not_stale(self):
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={
                "a": _entry(
                    _snap(50.0),
                    fetched_at_s=NOW_S - 100.0,
                    next_poll_at_s=NOW_S + 800.0,
                    poll_interval_s=700.0,
                ),
                "b": _entry(_snap(60.0), next_poll_at_s=NOW_S + 300.0),
            },
        )
        h.tick()
        assert h.fetch.calls == []

    def test_stale_plan_needs_sub_limit_usage(self):
        # An exhausted row on a wide plan is a reset-park, not staleness —
        # refetching it would spend budget the park exists to save.
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={
                "a": _entry(
                    _snap(100.0),
                    fetched_at_s=NOW_S - 400.0,
                    next_poll_at_s=NOW_S + 800.0,
                    poll_interval_s=700.0,
                ),
                "b": _entry(
                    _snap(100.0, NOW_S + 5000.0),
                    next_poll_at_s=NOW_S + 5000.0,
                    poll_interval_s=7200.0,
                ),
            },
        )
        h.tick()
        assert h.fetch.calls == []

    def test_stale_plan_marginal_headroom_counts(self):
        # pct 99.5 < 100 is still sub-limit usage — the row is stale. With no
        # candidate to escalate over, the stale plan is the only fetch path.
        h = _Harness(
            accounts=[_account("a")],
            credentialed={"a"},
            identity=_identity("a"),
            cache_rows={
                "a": _entry(
                    _snap(99.5),
                    fetched_at_s=NOW_S - 400.0,
                    next_poll_at_s=NOW_S + 800.0,
                    poll_interval_s=700.0,
                ),
            },
            reports={"a": _report(_snap(99.5))},
        )
        h.tick()
        assert h.fetch.calls == [("a", True, True, 90.0)]

    def test_overslept_plan_fetches_even_when_not_stale(self):
        # An impossibly-wide deadline is its own fetch reason — it must not
        # also require the stale-plan shape (or both would have to hold).
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={
                "a": _entry(
                    _snap(50.0),
                    fetched_at_s=NOW_S - 100.0,
                    next_poll_at_s=NOW_S + 800.0,
                    poll_interval_s=200.0,
                ),
                "b": _entry(_snap(60.0), next_poll_at_s=NOW_S + 300.0),
            },
            reports={"a": _report(_snap(50.0))},
        )
        h.tick()
        fetched = {name for name, *_ in h.fetch.calls}
        assert fetched == {"a"}
