"""AutoEngine.tick — the whole decide-switch-record pipeline, hermetically."""

from contextlib import AbstractContextManager

from support.engine_harness import NOW_S
from support.engine_harness import EngineHarness as _Harness
from support.engine_harness import account as _account
from support.engine_harness import entry as _entry
from support.engine_harness import identity as _identity
from support.engine_harness import report as _report
from support.engine_harness import snap as _snap
from support.fake_active_identity import FakeActiveIdentity
from support.in_memory_auto_state import InMemoryAutoState

from claude_acc_manager.accounts.application.ports import SwitchResult
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.auto.application.auto_engine import AutoEngine
from claude_acc_manager.auto.domain.auto_event import (
    AllExhaustedEvent,
    AutoEvent,
    ErrorEvent,
    NoSwitchEvent,
    PollEvent,
    QuarantinedEvent,
    SwitchEvent,
    TickOutcome,
)
from claude_acc_manager.auto.domain.auto_state import AutoState
from claude_acc_manager.settings.domain.settings_spec import AutoSettings
from claude_acc_manager.usage.domain.usage_cache_entry import UsageCacheEntry


def _reasons(events: list[AutoEvent]) -> list[str]:
    return [e.reason for e in events if isinstance(e, NoSwitchEvent)]


class TestNoActive:
    def test_logged_out_is_no_action(self):
        h = _Harness(accounts=[], credentialed=set(), identity=None)
        outcome = h.tick()
        assert outcome == TickOutcome.NO_ACTION
        assert h.events == [
            PollEvent(
                active=None,
                headroom={},
                threshold=90.0,
                fetch_errors={},
                windows={},
            ),
            NoSwitchEvent(reason="no-active-account", detail="log in and run 'cam add' first"),
        ]

    def test_unmanaged_live_login_is_refused(self):
        h = _Harness(accounts=[_account("work")], credentialed=set(), identity=_identity(None))
        outcome = h.tick()
        assert outcome == TickOutcome.NO_ACTION
        assert h.events == [
            PollEvent(
                active=None,
                headroom={},
                threshold=90.0,
                fetch_errors={},
                windows={},
            ),
            NoSwitchEvent(
                reason="unmanaged-active-account",
                detail="run 'cam add' to include it in rotation",
            ),
        ]
        assert h.executor.calls == []


class TestLoopFacingFields:
    def test_fresh_engine_reports_no_sleep_hints(self):
        h = _Harness(accounts=[], credentialed=set(), identity=None)
        assert h.engine.sleep_until_s is None
        assert h.engine.blocked_long_wait is False
        assert h.engine.next_poll_due_s is None


class TestTriggerGates:
    def test_below_threshold_stays_put(self):
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(50.0))},
            reports={"a": _report(_snap(50.0))},
        )
        outcome = h.tick()
        assert outcome == TickOutcome.NO_ACTION
        assert h.events == [
            PollEvent(
                active="a",
                headroom={"a": 50.0, "b": None},
                threshold=90.0,
                fetch_errors={},
                windows={"a": {"5h": 50.0}},
            ),
            NoSwitchEvent(reason="below-threshold", detail="50% < 90%"),
        ]
        assert h.engine.sleep_until_s is None
        assert h.engine.blocked_long_wait is False

    def test_unknown_active_usage_is_no_action(self):
        # no failover axis: unreadable active → NO_ACTION, normal cadence
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={"a": _entry(None)},
            reports={"a": _report(None)},
        )
        outcome = h.tick()
        assert outcome == TickOutcome.NO_ACTION
        assert h.events == [
            PollEvent(
                active="a",
                headroom={"a": None, "b": None},
                threshold=90.0,
                fetch_errors={},
                windows={},
            ),
            NoSwitchEvent(reason="active-usage-unknown", detail=""),
        ]

    def test_proactive_respects_cooldown(self):
        state = AutoState(last_switch_at_s=NOW_S - 100.0, last_switch_from="b", last_switch_to="a")
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(95.0))},
            reports={"a": _report(_snap(95.0)), "b": _report(_snap(10.0))},
            state=state,
        )
        outcome = h.tick()
        assert outcome == TickOutcome.NO_ACTION
        assert h.events == [
            PollEvent(
                active="a",
                headroom={"a": 5.0, "b": 90.0},
                threshold=90.0,
                fetch_errors={},
                windows={"a": {"5h": 95.0}, "b": {"5h": 10.0}},
            ),
            NoSwitchEvent(reason="cooldown", detail=""),
        ]
        # The early cooldown check must decide before freshening — a mutant
        # skipping it still lands on the locked recheck, but pays a freshen.
        assert h.freshen.calls == []

    def test_at_limit_ignores_cooldown(self):
        # at-limit is an escape: the cooldown must not bar it
        state = AutoState(last_switch_at_s=NOW_S - 100.0, last_switch_from="b", last_switch_to="a")
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(100.0))},
            reports={"a": _report(_snap(100.0)), "b": _report(_snap(10.0))},
            state=state,
            switch_result=SwitchResult(outcome="switched", target="b", previous="a"),
        )
        outcome = h.tick()
        assert outcome == TickOutcome.SWITCHED
        assert h.executor.calls == [(AccountName("b"), False)]
        assert h.events[-1] == SwitchEvent(trigger="at-limit", from_name="a", to_name="b")
        state = h.auto_state.load()
        assert state.left_headroom == 0.0
        assert state.left_recovery_at_s is None  # no provable reset → inf → None


class TestCandidateSelection:
    def test_no_candidates_is_blocked(self):
        h = _Harness(
            accounts=[_account("a")],
            credentialed=set(),
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(95.0))},
            reports={"a": _report(_snap(95.0))},
        )
        outcome = h.tick()
        assert outcome == TickOutcome.BLOCKED
        assert h.events[-1] == NoSwitchEvent(reason="no-candidates", detail="")
        assert h.engine.blocked_long_wait

    def test_credentialed_active_alone_is_still_no_candidates(self):
        # The active must be excluded from its own candidate list even when
        # it is enabled and credentialed — a self-pick is not a switch.
        h = _Harness(
            accounts=[_account("a")],
            credentialed={"a"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(95.0))},
            reports={"a": _report(_snap(95.0))},
        )
        outcome = h.tick()
        assert outcome == TickOutcome.BLOCKED
        assert _reasons(h.events) == ["no-candidates"]
        assert h.executor.calls == []

    def test_disabled_and_uncredentialed_are_not_candidates(self):
        h = _Harness(
            accounts=[_account("a"), _account("b", enabled=False), _account("c")],
            credentialed=set(),  # c has no parked credential either
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(95.0))},
            reports={"a": _report(_snap(95.0))},
        )
        outcome = h.tick()
        assert outcome == TickOutcome.BLOCKED
        assert _reasons(h.events) == ["no-candidates"]

    def test_unrankable_candidates_blocked(self):
        # b is below threshold but misses the hysteresis margin (15-8=7 < 10)
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(92.0))},
            reports={"a": _report(_snap(92.0)), "b": _report(_snap(85.0))},
        )
        outcome = h.tick()
        assert outcome == TickOutcome.BLOCKED
        assert h.events[-1] == NoSwitchEvent(
            reason="no-qualifying-candidate",
            detail=(
                "no candidate is below the threshold and better than the "
                "active account by the hysteresis margin, or usage is "
                "unreadable this tick"
            ),
        )

    def test_nearly_exhausted_candidate_is_not_all_exhausted(self):
        # b's headroom is positive (0.5) — thin, but not "at the limit", so
        # the fleet is unrankable rather than all-exhausted.
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(95.0)), "b": _entry(_snap(99.5))},
            reports={"a": _report(_snap(95.0)), "b": _report(_snap(99.5))},
        )
        outcome = h.tick()
        assert outcome == TickOutcome.BLOCKED
        assert _reasons(h.events) == ["no-qualifying-candidate"]
        assert not h.engine.sleep_until_s

    def test_unreadable_candidates_is_no_comparison(self):
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(95.0)), "b": _entry(None)},
            reports={"a": _report(_snap(95.0)), "b": _report(None)},
        )
        outcome = h.tick()
        assert outcome == TickOutcome.BLOCKED
        assert h.events[-1] == NoSwitchEvent(
            reason="no-comparison", detail="no candidate has readable usage"
        )

    def test_all_exhausted_emits_event_and_sleep_target(self):
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(100.0)), "b": _entry(_snap(100.0))},
            reports={
                "a": _report(_snap(100.0, NOW_S + 7200.0)),
                "b": _report(_snap(100.0, NOW_S + 3600.0)),
            },
        )
        outcome = h.tick()
        assert outcome == TickOutcome.BLOCKED
        assert h.events[-1] == AllExhaustedEvent(earliest_reset_at_s=NOW_S + 3600.0)
        assert h.engine.sleep_until_s == NOW_S + 3600.0 + 60.0
        assert h.engine.blocked_long_wait


class TestSwitchPath:
    def test_proactive_switch_records_departure_state(self):
        # a at 95% (proactive); b at 20% clears the 10pt hysteresis margin
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(95.0))},
            reports={
                "a": _report(_snap(95.0, NOW_S + 3600.0)),
                "b": _report(_snap(20.0, NOW_S + 1800.0)),
            },
            switch_result=SwitchResult(outcome="switched", target="b", previous="a"),
        )
        outcome = h.tick()
        assert outcome == TickOutcome.SWITCHED
        assert h.events[-1] == SwitchEvent(trigger="proactive", from_name="a", to_name="b")
        assert h.auto_state.lock_holds == 1
        state = h.auto_state.load()
        assert state.last_switch_at_s == NOW_S
        assert state.last_switch_from == "a"
        assert state.last_switch_to == "b"
        assert state.left_headroom == 5.0
        assert state.left_recovery_at_s == NOW_S + 3600.0

    def test_freshen_dead_quarantines_and_falls_through(self):
        # b ranks first (90 pts headroom) but its lineage is dead — quarantine
        # it and take c (50 pts) instead
        h = _Harness(
            accounts=[_account("a"), _account("b"), _account("c")],
            credentialed={"b", "c"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(100.0))},
            reports={
                "a": _report(_snap(100.0)),
                "b": _report(_snap(10.0)),
                "c": _report(_snap(50.0)),
            },
            freshen={"b": "dead"},
            switch_result=SwitchResult(outcome="switched", target="c", previous="a"),
        )
        outcome = h.tick()
        assert outcome == TickOutcome.SWITCHED
        assert h.quarantine.calls == ["b"]
        assert QuarantinedEvent(name="b", reason="invalid_grant") in h.events
        assert h.freshen.calls == ["b", "c"]
        assert h.executor.calls == [(AccountName("c"), False)]

    def test_transient_freshen_falls_through_to_next_candidate(self):
        # b ranks first but its freshen is transient — the engine must try c
        # rather than giving up on the whole ranked list.
        h = _Harness(
            accounts=[_account("a"), _account("b"), _account("c")],
            credentialed={"b", "c"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(100.0))},
            reports={
                "a": _report(_snap(100.0)),
                "b": _report(_snap(10.0)),
                "c": _report(_snap(50.0)),
            },
            freshen={"b": "transient"},
            switch_result=SwitchResult(outcome="switched", target="c", previous="a"),
        )
        outcome = h.tick()
        assert outcome == TickOutcome.SWITCHED
        assert h.freshen.calls == ["b", "c"]
        assert h.quarantine.calls == []
        assert h.executor.calls == [(AccountName("c"), False)]

    def test_all_freshen_dead_is_blocked_not_error(self):
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(100.0))},
            reports={"a": _report(_snap(100.0)), "b": _report(_snap(10.0))},
            freshen={"b": "dead"},
        )
        outcome = h.tick()
        assert outcome == TickOutcome.BLOCKED
        assert h.events[-1] == NoSwitchEvent(reason="no-viable-target", detail="")
        assert h.quarantine.calls == ["b"]

    def test_all_freshen_transient_is_error(self):
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(100.0))},
            reports={"a": _report(_snap(100.0)), "b": _report(_snap(10.0))},
            freshen={"b": "transient"},
        )
        outcome = h.tick()
        assert outcome == TickOutcome.ERROR
        assert h.events[-1] == ErrorEvent(
            message="could not freshen any candidate (network?)", transient=True
        )
        assert h.executor.calls == []

    def test_dry_run_decides_without_mutating(self):
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(100.0))},
            reports={"a": _report(_snap(100.0)), "b": _report(_snap(10.0))},
            dry_run=True,
        )
        outcome = h.tick()
        assert outcome == TickOutcome.SWITCHED
        assert h.events[-1] == SwitchEvent(
            trigger="at-limit", from_name="a", to_name="b", dry_run=True
        )
        assert h.freshen.calls == []  # freshening is a mutation
        assert h.executor.calls == []
        assert h.auto_state.lock_holds == 0
        assert h.auto_state.load() == AutoState()

    def test_default_construction_performs_real_switches(self):
        # Omitting dry_run must mean a real switch — the engine's default is
        # the production path, not a preview.
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(100.0))},
            reports={"a": _report(_snap(100.0)), "b": _report(_snap(10.0))},
        )
        h.engine = AutoEngine(
            settings=AutoSettings(),
            active_identity=FakeActiveIdentity(_identity("a")),
            store=h.store,
            account_files=h.files,
            usage_cache=h.cache,
            fetch=h.fetch,
            freshen=h.freshen,
            quarantine=h.quarantine,
            switch_executor=h.executor,
            auto_state=h.auto_state,
            clock=h.clock,
            emit=h.events.append,
        )
        outcome = h.engine.tick()
        assert outcome == TickOutcome.SWITCHED
        assert h.executor.calls == [(AccountName("b"), False)]

    def test_switch_without_previous_records_the_resolved_current(self):
        # A transaction that can't name the previous account still leaves the
        # no-return snapshot pointing at the account we actually left.
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(100.0))},
            reports={"a": _report(_snap(100.0)), "b": _report(_snap(10.0))},
            switch_result=SwitchResult(outcome="switched", target="b", previous=None),
        )
        outcome = h.tick()
        assert outcome == TickOutcome.SWITCHED
        assert h.events[-1] == SwitchEvent(trigger="at-limit", from_name="a", to_name="b")
        assert h.auto_state.load().last_switch_from == "a"

    def test_failed_switch_result_is_no_action(self):
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(100.0))},
            reports={"a": _report(_snap(100.0)), "b": _report(_snap(10.0))},
            switch_result=SwitchResult(outcome="already-active", target="b", previous="a"),
        )
        outcome = h.tick()
        assert outcome == TickOutcome.NO_ACTION
        assert h.events[-1] == NoSwitchEvent(reason="already-active", detail="already-active")
        assert h.auto_state.load() == AutoState()

    def test_standing_elsewhere_releases_the_no_return_bar(self):
        # Engine last switched b→c; someone moved the live slot to a by hand.
        # Standing on a, the bar protecting its own b→c move protects
        # nothing — b must rank again even though it has not recovered.
        state = AutoState(
            last_switch_at_s=NOW_S - 3600.0,
            last_switch_from="b",
            last_switch_to="c",
            left_headroom=2.0,
            left_recovery_at_s=NOW_S + 1000.0,
        )
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(95.0))},
            reports={
                "a": _report(_snap(95.0, NOW_S + 7200.0)),
                "b": _report(_snap(98.0, NOW_S + 1800.0)),
            },
            state=state,
            switch_result=SwitchResult(outcome="switched", target="b", previous="a"),
        )
        outcome = h.tick()
        assert outcome == TickOutcome.SWITCHED
        assert h.events[-1] == SwitchEvent(trigger="proactive", from_name="a", to_name="b")
        assert h.executor.calls == [(AccountName("b"), False)]


class _CooldownOnLockAutoState(InMemoryAutoState):
    """Flips to a cooled-down state when the decision lock is acquired.

    Simulates a concurrent engine writing between the tick's early check
    and the locked recheck — the race the lock exists to serialize.
    """

    def locked(self) -> AbstractContextManager[None]:
        self._state = AutoState(last_switch_at_s=NOW_S - 50.0)
        return super().locked()


class TestLockedRecheck:
    def test_cooldown_won_inside_the_lock_aborts(self):
        auto_state = _CooldownOnLockAutoState(AutoState())
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(95.0))},
            reports={"a": _report(_snap(95.0)), "b": _report(_snap(10.0))},
            auto_state_port=auto_state,
        )
        outcome = h.tick()
        assert outcome == TickOutcome.NO_ACTION
        assert h.events[-1] == NoSwitchEvent(reason="cooldown")
        assert h.auto_state.lock_holds == 1
        assert h.executor.calls == []


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


class TestNeverRaises:
    def test_port_exception_becomes_error_event(self):
        h = _Harness(accounts=[], credentialed=set(), identity=None)
        h.engine = AutoEngine(
            settings=AutoSettings(),
            active_identity=_RaisingIdentity(),
            store=h.store,
            account_files=h.files,
            usage_cache=h.cache,
            fetch=h.fetch,
            freshen=h.freshen,
            quarantine=h.quarantine,
            switch_executor=h.executor,
            auto_state=h.auto_state,
            clock=h.clock,
            emit=h.events.append,
        )
        outcome = h.engine.tick()
        assert outcome == TickOutcome.ERROR
        assert h.events == [ErrorEvent(message="RuntimeError: boom")]


class _RaisingIdentity:
    def execute(self):
        raise RuntimeError("boom")
