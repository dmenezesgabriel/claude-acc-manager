"""AutoEngine.run_loop — tick-cadence-sleep over the same harness.

The loop runs on a background thread and the tests drive it by watching
``h.events``/``h.fetch.calls`` fill up, then ``stop()``-ing — the waits are
real (``threading.Event.wait``), so the only timing assumption is that a
ticked event reaches the sink, never a wall-clock delay.
"""

import threading
import time
from collections.abc import Callable

import pytest
from support.engine_harness import NOW_S
from support.engine_harness import EngineHarness as _Harness
from support.engine_harness import account as _account
from support.engine_harness import entry as _entry
from support.engine_harness import identity as _identity
from support.engine_harness import report as _report
from support.engine_harness import snap as _snap
from support.fake_active_identity import FakeActiveIdentity

from claude_acc_manager.accounts.application.ports import (
    ActiveAccountStatus,
    ActiveIdentityPort,
)
from claude_acc_manager.auto.application.auto_engine import AutoEngine
from claude_acc_manager.auto.domain.auto_event import (
    AutoEvent,
    NoSwitchEvent,
    SleepEvent,
    TickOutcome,
)
from claude_acc_manager.auto.domain.services import loop_delay
from claude_acc_manager.settings.domain.settings_spec import AutoSettings


def _until(predicate: Callable[[], bool], timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    return predicate()


def _run(engine: AutoEngine) -> threading.Thread:
    thread = threading.Thread(target=engine.run_loop, daemon=True)
    thread.start()
    return thread


def _stop(engine: AutoEngine, thread: threading.Thread) -> None:
    engine.stop()
    thread.join(timeout=5.0)
    assert not thread.is_alive()


def _sleeps(events: list[AutoEvent]) -> list[SleepEvent]:
    return [e for e in events if isinstance(e, SleepEvent)]


class TestStop:
    def test_stop_before_start_exits_without_a_tick(self):
        h = _Harness(
            accounts=[_account("a")],
            credentialed={"a"},
            identity=_identity("a"),
            reports={"a": _report(_snap(50.0))},
        )
        h.engine.stop()
        assert h.engine.run_loop() == 0
        assert h.events == []
        assert h.fetch.calls == []

    def test_stop_during_the_sleep_wakes_it(self):
        # interval 60s → the sleep is ~54-66s; stop() must not wait it out
        h = _Harness(
            accounts=[_account("a")],
            credentialed={"a"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(50.0), next_poll_at_s=NOW_S + 300.0)},
            settings=AutoSettings(interval_seconds=60.0),
        )
        thread = _run(h.engine)
        assert _until(lambda: h.events)
        _stop(h.engine, thread)

    def test_stop_during_a_long_blocked_sleep_wakes_it(self):
        # the no-candidates long wait is 300s — the biggest sleep there is
        h = _Harness(
            accounts=[_account("a")],
            credentialed={"a"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(95.0))},
            reports={"a": _report(_snap(95.0))},
        )
        thread = _run(h.engine)
        assert _until(lambda: _sleeps(h.events))
        _stop(h.engine, thread)


class TestCadence:
    def test_the_loop_keeps_ticking(self):
        # a tiny interval lets several real sleeps elapse in one test
        h = _Harness(
            accounts=[_account("a")],
            credentialed={"a"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(50.0))},
            reports={"a": _report(_snap(50.0))},
            settings=AutoSettings(interval_seconds=0.05),
        )
        thread = _run(h.engine)
        assert _until(lambda: len(h.fetch.calls) >= 3)
        _stop(h.engine, thread)

    def test_a_failing_tick_does_not_kill_the_loop(self):
        h = _Harness(accounts=[], credentialed=set(), identity=None)
        h.engine = AutoEngine(
            settings=AutoSettings(interval_seconds=0.05),
            active_identity=_RaisingThenOk(FakeActiveIdentity(None)),
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
        thread = _run(h.engine)
        # the second tick resolves cleanly — the loop outlived the first error
        assert _until(
            lambda: (
                [e.reason for e in h.events if isinstance(e, NoSwitchEvent)]
                == ["no-active-account"]
            )
        )
        _stop(h.engine, thread)


class _RaisingThenOk(ActiveIdentityPort):
    """Booms once, then delegates to the real port — a transient blip."""

    def __init__(self, delegate: ActiveIdentityPort) -> None:
        self._delegate = delegate
        self._raised = False

    def execute(self) -> ActiveAccountStatus | None:
        if not self._raised:
            self._raised = True
            raise RuntimeError("boom")
        return self._delegate.execute()


class TestSleepEvent:
    def test_a_normal_cadence_sleep_stays_quiet(self):
        h = _Harness(
            accounts=[_account("a")],
            credentialed={"a"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(50.0), next_poll_at_s=NOW_S + 300.0)},
            settings=AutoSettings(interval_seconds=60.0),
        )
        thread = _run(h.engine)
        assert _until(lambda: h.events)
        _stop(h.engine, thread)
        assert _sleeps(h.events) == []

    def test_a_short_block_keeps_the_normal_cadence(self):
        # hysteresis-blocked (b misses the margin) — recheck every interval
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(92.0))},
            reports={"a": _report(_snap(92.0)), "b": _report(_snap(85.0))},
            settings=AutoSettings(interval_seconds=60.0),
        )
        thread = _run(h.engine)
        assert _until(lambda: h.events)
        _stop(h.engine, thread)
        assert _sleeps(h.events) == []

    def test_no_candidates_sleeps_the_fallback_with_an_event(self):
        h = _Harness(
            accounts=[_account("a")],
            credentialed={"a"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(95.0))},
            reports={"a": _report(_snap(95.0))},
            settings=AutoSettings(interval_seconds=60.0),
        )
        thread = _run(h.engine)
        assert _until(lambda: _sleeps(h.events))
        _stop(h.engine, thread)
        assert _sleeps(h.events) == [
            SleepEvent(seconds=300.0, until="2023-11-14T22:18:20Z")  # NOW_S + 300
        ]

    def test_all_exhausted_sleeps_toward_the_capped_reset(self):
        # earliest reset is NOW+3600 (+60 slack) → capped at MAX_SLEEP_S
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(100.0)), "b": _entry(_snap(100.0))},
            reports={
                "a": _report(_snap(100.0, NOW_S + 7200.0)),
                "b": _report(_snap(100.0, NOW_S + 3600.0)),
            },
            settings=AutoSettings(interval_seconds=60.0),
        )
        thread = _run(h.engine)
        assert _until(lambda: _sleeps(h.events))
        _stop(h.engine, thread)
        assert _sleeps(h.events) == [
            SleepEvent(seconds=600.0, until="2023-11-14T22:23:20Z")  # NOW_S + 600
        ]

    def test_a_reset_sleep_just_above_the_emission_bar_emits(self):
        # earliest reset NOW+60 → sleep_until NOW+120 → delay 120 > 1.5×60
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(100.0)), "b": _entry(_snap(100.0))},
            reports={
                "a": _report(_snap(100.0, NOW_S + 7200.0)),
                "b": _report(_snap(100.0, NOW_S + 60.0)),
            },
            settings=AutoSettings(interval_seconds=60.0),
        )
        thread = _run(h.engine)
        assert _until(lambda: _sleeps(h.events))
        _stop(h.engine, thread)
        assert _sleeps(h.events) == [
            SleepEvent(seconds=120.0, until="2023-11-14T22:15:20Z")  # NOW_S + 120
        ]

    def test_a_reset_sleep_at_the_emission_bar_stays_quiet(self):
        # earliest reset NOW+30 → sleep_until NOW+90 → delay exactly 1.5×60:
        # the bar is strictly-above, so this sleep is not announced.
        h = _Harness(
            accounts=[_account("a"), _account("b")],
            credentialed={"b"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(100.0)), "b": _entry(_snap(100.0))},
            reports={
                "a": _report(_snap(100.0, NOW_S + 7200.0)),
                "b": _report(_snap(100.0, NOW_S + 30.0)),
            },
            settings=AutoSettings(interval_seconds=60.0),
        )
        thread = _run(h.engine)
        assert _until(lambda: h.events)
        # The event would already be in the sink by now — settle, then stop.
        time.sleep(0.3)
        _stop(h.engine, thread)
        assert _sleeps(h.events) == []

    def test_the_plan_deadline_reaches_the_delay_policy(self, monkeypatch: pytest.MonkeyPatch):
        seen: list[dict[str, object]] = []
        real_next_delay = loop_delay.next_delay

        def spy(outcome: TickOutcome, **kwargs: object) -> float:
            seen.append(kwargs)
            return real_next_delay(outcome, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(loop_delay, "next_delay", spy)
        h = _Harness(
            accounts=[_account("a")],
            credentialed={"a"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(50.0), next_poll_at_s=NOW_S + 123.0)},
            settings=AutoSettings(interval_seconds=60.0),
        )
        thread = _run(h.engine)
        assert _until(lambda: seen)
        _stop(h.engine, thread)
        assert seen[0]["next_poll_due_s"] == NOW_S + 123.0


class TestNextPollDue:
    def test_the_active_row_due_time_is_published(self):
        h = _Harness(
            accounts=[_account("a")],
            credentialed={"a"},
            identity=_identity("a"),
            cache_rows={"a": _entry(_snap(50.0), next_poll_at_s=NOW_S + 123.0)},
        )
        h.tick()
        assert h.engine.next_poll_due_s == NOW_S + 123.0

    def test_it_resets_each_tick(self):
        h = _Harness(accounts=[], credentialed=set(), identity=None)
        h.engine.next_poll_due_s = NOW_S + 999.0
        h.tick()
        assert h.engine.next_poll_due_s is None
