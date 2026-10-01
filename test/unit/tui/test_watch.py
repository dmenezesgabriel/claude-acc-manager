"""The watch screen — a hands-off monitor that can arm selection.

Monitor mode shows every account as a full card with no cursor at all;
``s`` arms selection (the cursor lands on the active account), Enter
switches and disarms in place — you keep watching on the new account.
Esc/q disarm first, then pop back to whatever pushed the screen.
"""

import threading
from pathlib import Path

from support.tui_app import settle_workers, wired_app
from textual.widgets import ListView, Static

from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.tui.account_list import WatchScreen
from claude_acc_manager.tui.app import CamApp
from claude_acc_manager.tui.dashboard import DashboardScreen

WATCH_TITLE = "watching all accounts"
SELECT_TITLE = "switch to which account? · enter confirm · esc cancel"


def _spy_notify(app: CamApp) -> list[tuple[str, dict[str, object]]]:
    """Record ``notify`` calls as ``(message, kwargs)`` pairs."""
    calls: list[tuple[str, dict[str, object]]] = []
    app.notify = lambda message, **kw: calls.append((message, kw))  # type: ignore[method-assign]
    return calls


def _list(app: CamApp) -> ListView:
    """The watch screen's account list."""
    return app.screen.query_one("#accounts", ListView)


def _title(app: CamApp) -> str:
    """The watch screen's current title line."""
    return str(app.screen.query_one("#list-title", Static).content)


async def _open_watch(pilot) -> None:
    """From the dashboard, ``w`` stacks the watch monitor."""
    await pilot.press("w")
    await pilot.pause()


class TestMonitorMode:
    async def test_opens_on_the_watch_title_with_no_cursor(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path, active_name="work")
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_watch(pilot)
            assert isinstance(app.screen, WatchScreen)
            assert _title(app) == WATCH_TITLE
            assert _list(app).index is None

    async def test_enter_is_inert_until_selection_is_armed(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        notes = _spy_notify(app)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_watch(pilot)
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, WatchScreen)
            assert notes == []

    async def test_j_and_k_scroll_instead_of_moving_a_cursor(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_watch(pilot)
            scrolls: list[tuple[str, bool]] = []
            listview = _list(app)
            listview.scroll_down = lambda **kw: scrolls.append(("down", kw["animate"]))  # type: ignore[method-assign]
            listview.scroll_up = lambda **kw: scrolls.append(("up", kw["animate"]))  # type: ignore[method-assign]
            await pilot.press("j")
            await pilot.press("k")
            await pilot.pause()
            assert _list(app).index is None
            # instant jumps — animated scrolls would fight the 3s poll redraw
            assert scrolls == [("down", False), ("up", False)]

    async def test_the_title_carries_the_refresh_status(self, tmp_path: Path) -> None:
        app, _api, _store, clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_watch(pilot)
            assert _title(app) == WATCH_TITLE
            clock.advance(61)
            app._update_refresh_status()
            await pilot.pause()
            assert _title(app) == f"{WATCH_TITLE} · {app.refresh_status}"
            assert app.refresh_status  # the suffix was non-empty

    async def test_a_member_change_never_grows_a_cursor(self, tmp_path: Path) -> None:
        app, _api, store, _clock = wired_app(tmp_path, names=("work", "personal", "alt"))
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_watch(pilot)
            store.remove(AccountName("alt"))
            app.request_refresh()
            await settle_workers(pilot)
            assert _list(app).index is None


class TestArmedSelection:
    def test_selection_starts_disarmed(self) -> None:
        # arrange / act
        screen = WatchScreen()

        # assert
        assert screen._selecting is False

    async def test_arming_before_the_first_snapshot_lands_on_active(self, tmp_path: Path) -> None:
        # the collect gate holds the snapshot at None — deterministic window
        # for "armed with nothing to cursor to yet"
        gate = threading.Event()
        app, _api, _store, _clock = wired_app(tmp_path, active_name="personal", collect_gate=gate)
        async with app.run_test() as pilot:
            await pilot.press("w")
            await pilot.pause()
            await pilot.press("s")
            await pilot.pause()
            assert app.snapshot is None
            assert _list(app).index is None
            gate.set()
            await settle_workers(pilot)
            assert _list(app).index == 1  # the build lands on the active row
            assert _title(app) == SELECT_TITLE

    async def test_a_member_change_while_armed_keeps_the_cursor(self, tmp_path: Path) -> None:
        app, _api, store, _clock = wired_app(
            tmp_path, names=("work", "personal", "alt"), active_name="work"
        )
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_watch(pilot)
            await pilot.press("s")
            await pilot.press("j")  # cursor onto personal
            store.remove(AccountName("alt"))
            app.request_refresh()
            await settle_workers(pilot)
            assert _list(app).index == 1  # preserved across the rebuild
            assert _title(app) == SELECT_TITLE  # still armed

    async def test_s_arms_selection_on_the_active_account(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path, active_name="personal")
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_watch(pilot)
            await pilot.press("s")
            await pilot.pause()
            assert _title(app) == SELECT_TITLE
            assert _list(app).index == 1
            assert _list(app).has_focus

    async def test_s_again_disarms(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path, active_name="work")
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_watch(pilot)
            await pilot.press("s")
            await pilot.press("s")
            await pilot.pause()
            assert _title(app) == WATCH_TITLE
            assert _list(app).index is None
            assert not _list(app).has_focus

    async def test_the_confirm_action_hides_until_armed(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_watch(pilot)
            screen = app.screen
            assert screen.check_action("select_highlighted", ()) is False
            await pilot.press("s")
            await pilot.pause()
            assert screen.check_action("select_highlighted", ()) is True

    async def test_j_and_k_move_the_cursor_once_armed(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_watch(pilot)
            await pilot.press("s")
            await pilot.press("j")
            await pilot.pause()
            assert _list(app).index == 1
            await pilot.press("k")
            await pilot.pause()
            assert _list(app).index == 0

    async def test_status_updates_do_not_touch_the_select_title(self, tmp_path: Path) -> None:
        app, _api, _store, clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_watch(pilot)
            await pilot.press("s")
            clock.advance(61)
            app._update_refresh_status()
            await pilot.pause()
            assert _title(app) == SELECT_TITLE

    async def test_enter_switches_and_keeps_watching(self, tmp_path: Path) -> None:
        app, _api, store, _clock = wired_app(tmp_path, active_name="work")
        notes = _spy_notify(app)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_watch(pilot)
            await pilot.press("s")
            await pilot.press("j")  # personal
            await pilot.press("enter")
            await settle_workers(pilot)
            assert isinstance(app.screen, WatchScreen)
            assert notes[-1][0] == "switched to 'personal' (was 'work')"
            active = store.active()
            assert active is not None and active.name.value == "personal"
            # disarmed: hands-off again, cursor hidden
            assert app.screen._selecting is False
            assert _list(app).index is None
            assert _title(app) == WATCH_TITLE

    async def test_escape_disarms_first_then_pops(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_watch(pilot)
            await pilot.press("s")
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, WatchScreen)
            assert app.screen._selecting is False
            assert _list(app).index is None
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, DashboardScreen)

    async def test_q_disarms_first_then_pops(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_watch(pilot)
            await pilot.press("s")
            await pilot.press("q")
            await pilot.pause()
            assert isinstance(app.screen, WatchScreen)
            await pilot.press("q")
            await pilot.pause()
            assert isinstance(app.screen, DashboardScreen)

    async def test_f_still_refreshes(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        notes = _spy_notify(app)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_watch(pilot)
            await pilot.press("f")
            await settle_workers(pilot)
            assert notes[-1][0] == "Refreshing usage…"
