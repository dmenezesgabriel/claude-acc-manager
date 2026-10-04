"""Terminal title writes and the unfocused-completion blink (slice T5).

Textual never writes a window title itself — the app emits an OSC 0
escape straight through ``driver.write``, so a spy on
``HeadlessDriver.write`` is the observation seam. Blink ticks are stepped
synchronously; no test sleeps real time.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from support.tui_app import settle_workers, wired_app
from textual.drivers.headless_driver import HeadlessDriver

from claude_acc_manager.tui.account_list import SwitchScreen, WatchScreen
from claude_acc_manager.tui.app import ActionToast
from claude_acc_manager.tui.autoview import AutoScreen

OSC = "\033]0;"
BEL = "\007"


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


def _done_ok(_result: object) -> ActionToast:
    return ActionToast("done", "information")


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
            app._blink_terminal_title()
            await pilot.pause()
            assert _wrote_title(title_writes, "* cam — dashboard")


class TestTitleBlink:
    async def test_action_completion_blinks_when_unfocused(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            app.app_focus = False
            app._action_done("ok", _done_ok, "failed")
            await settle_workers(pilot)
            assert app.terminal_title_blink is True
            assert app._title_blink_timer is not None

    async def test_action_completion_while_focused_stays_quiet(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            app._action_done("ok", _done_ok, "failed")
            await settle_workers(pilot)
            assert app.terminal_title_blink is False
            assert app._title_blink_timer is None

    async def test_a_failed_action_also_blinks_when_unfocused(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            app.app_focus = False
            app._action_done(RuntimeError("boom"), _done_ok, "failed")
            await settle_workers(pilot)
            assert app.terminal_title_blink is True

    async def test_blink_steps_toggle_then_stop_after_three_seconds(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test():
            app.app_focus = False
            app._blink_terminal_title()
            timer = app._title_blink_timer
            assert timer is not None
            states = []
            for step in range(app.TITLE_BLINK_TICKS):
                app._blink_title_step()
                states.append(app.terminal_title_blink)
                if step < app.TITLE_BLINK_TICKS - 1:
                    # an early-stop mutant ends the cycle a tick short
                    assert app._title_blink_timer is timer
            assert states == [False, True, False, True, False, False]
            assert app._title_blink_timer is None
            assert timer._task is None

    async def test_the_timer_steps_on_the_half_second(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        calls: list[tuple[float, object]] = []
        original = app.set_interval

        def spy(interval: float, callback: object, *args: object, **kwargs: object):
            calls.append((interval, callback))
            return original(interval, callback, *args, **kwargs)

        app.set_interval = spy  # type: ignore[method-assign]
        async with app.run_test():
            app.app_focus = False
            app._blink_terminal_title()
            assert (app.BLINK_INTERVAL_S, app._blink_title_step) in calls

    async def test_a_fresh_app_is_not_mid_blink(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        # pre-mount reads must avoid the reactive — its watcher needs a screen
        assert app._title_blink_ticks == 0
        assert app._title_blink_timer is None
        async with app.run_test():
            assert app.terminal_title_blink is False

    async def test_rearming_keeps_a_single_timer(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test():
            app.app_focus = False
            app._blink_terminal_title()
            first = app._title_blink_timer
            app._title_blink_ticks = 2
            app._blink_terminal_title()
            assert app._title_blink_timer is first
            assert app._title_blink_ticks == app.TITLE_BLINK_TICKS
