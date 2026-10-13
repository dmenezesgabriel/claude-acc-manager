"""``AutoEngine.tick`` — decide: no-active, loop fields, trigger gates, candidates.

The decide half of the tick pipeline, hermetically wired through
``support.engine_harness``.
"""

from support.engine_harness import NOW_S
from support.engine_harness import EngineHarness as _Harness
from support.engine_harness import account as _account
from support.engine_harness import entry as _entry
from support.engine_harness import identity as _identity
from support.engine_harness import report as _report
from support.engine_harness import snap as _snap

from claude_acc_manager.accounts.application.ports import SwitchResult
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.auto.domain.auto_event import (
    AllExhaustedEvent,
    AutoEvent,
    NoSwitchEvent,
    PollEvent,
    SwitchEvent,
    TickOutcome,
)
from claude_acc_manager.auto.domain.auto_state import AutoState


def _reasons(events: list[AutoEvent]) -> list[str]:
    return [e.reason for e in events if isinstance(e, NoSwitchEvent)]


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
