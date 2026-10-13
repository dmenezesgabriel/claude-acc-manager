"""``AutoEngine.tick`` — the switch path: execution, locks, quarantine, errors.

The mutate half of the tick — what happens once a candidate is chosen —
plus the engine's never-raise contract at the port boundary.
"""

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
    ErrorEvent,
    NoSwitchEvent,
    QuarantinedEvent,
    SwitchEvent,
    TickOutcome,
)
from claude_acc_manager.auto.domain.auto_state import AutoState
from claude_acc_manager.settings.domain.settings_spec import AutoSettings


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
            collector=h.collector,
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

    def test_no_return_bar_holds_while_still_on_the_landing(self):
        # Engine last switched b→a and still sits on a. Every measured
        # account is spent, so b outranks c on the recovery axis — but b is
        # exactly the account the bar protects: unrecovered since departure.
        # The bar must re-route the landing to c.
        state = AutoState(
            last_switch_at_s=NOW_S - 3600.0,
            last_switch_from="b",
            last_switch_to="a",
            left_headroom=4.0,
            left_recovery_at_s=NOW_S + 1000.0,
        )
        h = _Harness(
            accounts=[_account("a"), _account("b"), _account("c")],
            credentialed={"b", "c"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(95.0))},
            reports={
                "a": _report(_snap(95.0, NOW_S + 7200.0)),
                "b": _report(_snap(95.0, NOW_S + 1000.0)),
                "c": _report(_snap(96.0, NOW_S + 6000.0)),
            },
            state=state,
            switch_result=SwitchResult(outcome="switched", target="c", previous="a"),
        )
        outcome = h.tick()
        assert outcome == TickOutcome.SWITCHED
        assert h.events[-1] == SwitchEvent(trigger="proactive", from_name="a", to_name="c")
        assert h.executor.calls == [(AccountName("c"), False)]


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


class TestNeverRaises:
    def test_port_exception_becomes_error_event(self):
        h = _Harness(accounts=[], credentialed=set(), identity=None)
        h.engine = AutoEngine(
            settings=AutoSettings(),
            active_identity=_RaisingIdentity(),
            collector=h.collector,
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
