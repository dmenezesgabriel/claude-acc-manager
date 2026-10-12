"""Terminal title writes and the unfocused-completion blink.

Textual never writes a window title itself — the app emits an OSC 0
escape straight through ``driver.write``, so a spy on
``HeadlessDriver.write`` is the observation seam. Blink steps are driven
through the ``set_interval`` callback the app registered — captured, never
named — so no test sleeps real time.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from support.tui_app import settle_workers, wired_app
from textual.drivers.headless_driver import HeadlessDriver
from textual.timer import Timer

from claude_acc_manager.tui.account_list import SwitchScreen, WatchScreen
from claude_acc_manager.tui.app import CamApp
from claude_acc_manager.tui.autoview import AutoScreen

OSC = "\033]0;"
BEL = "\007"

IntervalCall = tuple[float, Callable[..., object], Timer]


@pytest.fixture
def title_writes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every raw payload written to the driver, captured before mount."""
    writes: list[str] = []
    original = HeadlessDriver.write

    def spy(self: HeadlessDriver, data: str) -> None:
        writes.append(data)
        original(self, data)

    monkeypatch.setattr(HeadlessDriver, "write", spy)
    return writes


def _wrote_title(writes: list[str], expected: str) -> bool:
    return any(f"{OSC}{expected}{BEL}" in payload for payload in writes)


def _spy_intervals(app: CamApp) -> list[IntervalCall]:
    """Capture every ``(interval, callback, timer)`` the app registers."""
    calls: list[IntervalCall] = []
    original = app.set_interval

    def spy(interval: float, callback: Callable[..., object], **kwargs: object) -> Timer:
        timer = original(interval, callback, **kwargs)
        calls.append((interval, callback, timer))
        return timer

    app.set_interval = spy  # type: ignore[method-assign]
    return calls


def _spy_stop(timer: Timer) -> list[bool]:
    """Record invocations of a captured timer's public ``stop``."""
    stops: list[bool] = []
    original = timer.stop

    def spy() -> None:
        stops.append(True)
        original()

    timer.stop = spy  # type: ignore[method-assign]
    return stops


def _blink_registration(calls: list[IntervalCall], app: CamApp) -> IntervalCall:
    """The one blink-interval registration among the app's timers."""
    blink = [c for c in calls if c[0] == app.BLINK_INTERVAL_S]
    assert len(blink) == 1
    return blink[0]


class TestTerminalTitle:
    async def test_mount_writes_the_dashboard_title(
        self, tmp_path: Path, title_writes: list[str]
    ) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test():
            assert _wrote_title(title_writes, "cam — dashboard")

    async def test_pushing_a_screen_rewrites_the_title(
        self, tmp_path: Path, title_writes: list[str]
    ) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            app.push_screen(SwitchScreen())
            await pilot.pause()
            assert _wrote_title(title_writes, "cam — switch")

    async def test_popping_restores_the_underneath_title(
        self, tmp_path: Path, title_writes: list[str]
    ) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            app.push_screen(SwitchScreen())
            await pilot.pause()
            title_writes.clear()
            app.pop_screen()
            await pilot.pause()
            assert _wrote_title(title_writes, "cam — dashboard")

    async def test_watch_and_auto_screens_have_titles(
        self, tmp_path: Path, title_writes: list[str]
    ) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            app.push_screen(WatchScreen())
            await pilot.pause()
            assert _wrote_title(title_writes, "cam — watch")
            app.pop_screen()
            await pilot.pause()
            app.push_screen(AutoScreen())
            await pilot.pause()
            assert _wrote_title(title_writes, "cam — auto")

    async def test_a_screen_without_title_writes_just_cam(
        self, tmp_path: Path, title_writes: list[str]
    ) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test():
            app.screen.title = None
            app.update_terminal_title()
            assert _wrote_title(title_writes, "cam")

    async def test_the_blink_marks_the_title(self, tmp_path: Path, title_writes: list[str]) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            app.app_focus = False
            app.blink_terminal_title()
            await pilot.pause()
            assert _wrote_title(title_writes, "* cam — dashboard")


class TestTitleBlink:
    # The armed blink toggles on a real half-second timer, so the marker's
    # reactive can be mid-cycle by the time workers settle — the starred
    # OSC-0 write is the deterministic observation.
    async def test_action_completion_blinks_when_unfocused(
        self, tmp_path: Path, title_writes: list[str]
    ) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            app.app_focus = False
            app.do_switch("personal")
            await settle_workers(pilot)
            assert _wrote_title(title_writes, "* cam — dashboard")

    async def test_action_completion_while_focused_stays_quiet(
        self, tmp_path: Path, title_writes: list[str]
    ) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            app.do_switch("personal")
            await settle_workers(pilot)
            assert app.terminal_title_blink is False
            assert not _wrote_title(title_writes, "* cam — dashboard")

    async def test_a_failed_action_also_blinks_when_unfocused(
        self, tmp_path: Path, title_writes: list[str]
    ) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            app.app_focus = False
            app.do_switch("ghost")
            await settle_workers(pilot)
            assert _wrote_title(title_writes, "* cam — dashboard")

    async def test_blink_steps_toggle_then_stop_after_three_seconds(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        intervals = _spy_intervals(app)
        async with app.run_test():
            app.app_focus = False
            app.blink_terminal_title()
            _interval, step, timer = _blink_registration(intervals, app)
            stops = _spy_stop(timer)
            states = []
            for n in range(app.TITLE_BLINK_TICKS):
                step()
                states.append(app.terminal_title_blink)
                if n < app.TITLE_BLINK_TICKS - 1:
                    # an early-stop mutant ends the cycle a tick short
                    assert stops == []
            assert states == [False, True, False, True, False, False]
            assert stops == [True]
            # ticks exhausted — a re-fired step is a no-op, never re-toggles
            step()
            assert app.terminal_title_blink is False

    async def test_the_timer_steps_on_the_half_second(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        intervals = _spy_intervals(app)
        async with app.run_test():
            app.app_focus = False
            app.blink_terminal_title()
            _interval, step, _timer = _blink_registration(intervals, app)
            # the registered callback is the blink toggle itself
            step()
            assert app.terminal_title_blink is False

    async def test_a_fresh_app_is_not_mid_blink(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        intervals = _spy_intervals(app)
        async with app.run_test():
            assert app.terminal_title_blink is False
            # mount registers the poll and status ticks, never a blink
            assert not [c for c in intervals if c[0] == app.BLINK_INTERVAL_S]

    async def test_rearming_keeps_a_single_timer(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        intervals = _spy_intervals(app)
        async with app.run_test():
            app.app_focus = False
            app.blink_terminal_title()
            _interval, step, timer = _blink_registration(intervals, app)
            stops = _spy_stop(timer)
            step()
            step()
            app.blink_terminal_title()
            # still exactly one registration, on the same live timer
            assert _blink_registration(intervals, app)[2] is timer
            assert stops == []
            # the re-arm reset the countdown — six fresh steps to the end
            remaining = []
            for _ in range(app.TITLE_BLINK_TICKS):
                step()
                remaining.append(app.terminal_title_blink)
            assert remaining == [False, True, False, True, False, False]
            assert stops == [True]
