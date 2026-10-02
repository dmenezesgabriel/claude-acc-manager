"""The switch screen — a live account list where Enter commits.

``AccountListScreen`` owns the snapshot-driven ListView (rebuild on
membership change, in-place updates otherwise, a brief ``flash`` on rows
whose measurement just advanced); ``SwitchScreen`` adds the cursor and
the Enter/``b`` dispatch into ``CamApp.do_switch`` / ``switch_best``.
"""

import asyncio
import threading
from dataclasses import replace
from pathlib import Path

from support.in_memory_usage_cache import InMemoryUsageCache
from support.tui_app import settle_workers, wired_app
from textual.widgets import ListView, Static

from claude_acc_manager.accounts.application.use_cases.switch_account import SwitchResult
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.tui.account_list import FLASH_S, SwitchScreen
from claude_acc_manager.tui.app import CamApp
from claude_acc_manager.tui.dashboard import DashboardScreen
from claude_acc_manager.tui.widgets import AccountItem
from claude_acc_manager.usage.domain.usage_cache_entry import (
    EMPTY_USAGE_CACHE_ENTRY,
    UsageCacheEntry,
)
from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot, UsageWindow


def _spy_notify(app: CamApp) -> list[tuple[str, dict[str, object]]]:
    """Record ``notify`` calls as ``(message, kwargs)`` pairs."""
    calls: list[tuple[str, dict[str, object]]] = []
    app.notify = lambda message, **kw: calls.append((message, kw))  # type: ignore[method-assign]
    return calls


def _list(app: CamApp) -> ListView:
    """The switch/watch screen's account list."""
    return app.screen.query_one("#accounts", ListView)


def _names(app: CamApp) -> list[str]:
    """The account name of every rendered row, in list order."""
    return [item.account_name.value for item in app.screen.query(AccountItem)]


def _flashed(app: CamApp) -> list[str]:
    """The account name of every row currently carrying ``flash``."""
    return [
        item.account_name.value for item in app.screen.query(AccountItem) if item.has_class("flash")
    ]


class _BlockingSwitch:
    """``execute`` parks the action thread until the test releases it."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.targets: list[object] = []

    def execute(
        self,
        target: AccountName | None = None,
        *,
        strategy: object = None,
        headroom: object = None,
        dry_run: bool = False,
    ) -> SwitchResult:
        self.targets.append(target)
        self.entered.set()
        self.release.wait(timeout=5)
        return SwitchResult(
            outcome="switched",
            target=target.value if target else None,
            previous="work",
        )


class _RaisingSwitch:
    """``execute`` raises — the action lane must surface the failure."""

    def execute(self, *args: object, **kwargs: object) -> SwitchResult:
        raise RuntimeError("boom")


async def _open_switch(pilot) -> None:
    """From the dashboard root menu, Enter on the first row opens switch."""
    await pilot.press("enter")
    await pilot.pause()


class TestOpening:
    async def test_menu_switch_opens_the_screen(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path, active_name="work")
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_switch(pilot)
            assert isinstance(app.screen, SwitchScreen)
            assert _list(app).has_focus
            title = app.screen.query_one("#list-title", Static)
            assert str(title.content) == "switch to which account?"

    async def test_s_binding_opens_it_too(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await pilot.press("s")
            await pilot.pause()
            assert isinstance(app.screen, SwitchScreen)

    async def test_opening_twice_never_stacks(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await pilot.press("s")
            await pilot.pause()
            depth = len(app.screen_stack)
            app.action_open_switch()
            await pilot.pause()
            assert len(app.screen_stack) == depth


class TestListContents:
    async def test_every_account_is_a_row_and_cursor_starts_on_active(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path, active_name="personal")
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_switch(pilot)
            assert _names(app) == ["work", "personal"]
            assert _list(app).index == 1

    async def test_no_active_login_lands_the_cursor_on_top(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_switch(pilot)
            assert _list(app).index == 0

    async def test_j_and_k_move_the_cursor(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_switch(pilot)
            await pilot.press("j")
            assert _list(app).index == 1
            await pilot.press("k")
            assert _list(app).index == 0


class TestListState:
    def test_the_screen_starts_without_membership_or_stamps(self) -> None:
        # arrange / act
        screen = SwitchScreen()

        # assert — the first snapshot takes the build path, not the diff path
        assert screen._names == []
        assert screen._stamps == {}

    async def test_index_boundaries_after_a_rebuild(self, tmp_path: Path) -> None:
        # ListView.validate_index clamps out-of-range writes, so the clamp
        # boundary in _index_after_build is only observable on the method.
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_switch(pilot)
            screen = app.screen
            assert isinstance(screen, SwitchScreen)
            snap = app.snapshot
            assert snap is not None
            assert screen._index_after_build(snap, False, 0) == 0
            assert screen._index_after_build(snap, False, 1) == 1
            assert screen._index_after_build(snap, False, 2) == 1  # past the end
            assert screen._index_after_build(snap, False, None) == 0


class TestSelection:
    async def test_enter_switches_and_pops(self, tmp_path: Path) -> None:
        app, _api, store, _clock = wired_app(tmp_path, active_name="work")
        notes = _spy_notify(app)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_switch(pilot)
            await pilot.press("j")  # personal
            await pilot.press("enter")
            await settle_workers(pilot)
            assert isinstance(app.screen, DashboardScreen)
            assert notes[-1][0] == "switched to 'personal' (was 'work')"
            assert notes[-1][1] == {"severity": "information"}
            active = store.active()
            assert active is not None and active.name.value == "personal"

    async def test_selecting_the_active_account_says_so(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path, active_name="work")
        notes = _spy_notify(app)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_switch(pilot)
            await pilot.press("enter")  # work is already active
            await settle_workers(pilot)
            assert notes[-1][0] == "'work' is already the active account"
            assert notes[-1][1] == {"severity": "warning"}

    async def test_back_keys_pop_to_the_dashboard(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_switch(pilot)
            for key in ("escape", "q", "s"):
                assert isinstance(app.screen, SwitchScreen)
                await pilot.press(key)
                await pilot.pause()
                assert isinstance(app.screen, DashboardScreen)
                await _open_switch(pilot)


def _seeded_entry(pct: float, now_s: float) -> UsageCacheEntry:
    """A fresh cache entry whose five-hour window sits at *pct*."""
    snapshot = UsageSnapshot(
        five_hour=UsageWindow(pct=pct, resets_at=None), seven_day=None, scoped=()
    )
    return replace(EMPTY_USAGE_CACHE_ENTRY, last_good=snapshot, fetched_at_s=now_s)


class TestBestPick:
    async def test_b_switches_to_the_roomiest_candidate(self, tmp_path: Path) -> None:
        cache = InMemoryUsageCache()
        now = 1_000_000.0
        cache.save("work", _seeded_entry(95.0, now))  # active, nearly exhausted
        cache.save("personal", _seeded_entry(10.0, now))
        app, _api, store, _clock = wired_app(tmp_path, active_name="work", usage_cache=cache)
        notes = _spy_notify(app)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_switch(pilot)
            await pilot.press("b")
            await settle_workers(pilot)
            assert notes[-1][0] == "switched to 'personal' (was 'work')"
            assert isinstance(app.screen, SwitchScreen)  # stays open

    async def test_b_when_already_best_announces_it(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path, active_name="work")
        notes = _spy_notify(app)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_switch(pilot)
            await pilot.press("b")
            await settle_workers(pilot)
            assert notes[-1][0] == "the active account already has the most headroom"
            assert notes[-1][1] == {"severity": "warning"}


class TestActionGuards:
    async def test_the_action_worker_carries_its_label_and_lane(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        captured: list[dict[str, object]] = []
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            original = app.run_worker
            app.run_worker = lambda work, **kw: (  # type: ignore[method-assign]
                captured.append(kw),
                original(work, **kw),
            )[1]
            app.do_switch("personal")
            assert captured[-1] == {
                "thread": True,
                "group": "action",
                "exit_on_error": False,
                "name": "switch to personal",
            }
            await settle_workers(pilot)  # busy must clear before a second action
            app.action_switch_best()
            assert captured[-1]["name"] == "switch (best)"
            await settle_workers(pilot)

    async def test_while_an_action_runs_the_lane_reports_busy(self, tmp_path: Path) -> None:
        blocking = _BlockingSwitch()
        app, _api, _store, _clock = wired_app(tmp_path, switch=blocking)  # type: ignore[arg-type]
        notes = _spy_notify(app)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app.do_switch("personal")
            assert await asyncio.to_thread(blocking.entered.wait, 5)
            assert app.busy is True
            app.do_switch("work")
            assert notes == [("another action is still running", {"severity": "warning"})]
            blocking.release.set()
            await settle_workers(pilot)
            assert app.busy is False
            assert notes[-1][0] == "switched to 'personal' (was 'work')"
            assert blocking.targets == [AccountName("personal")]

    async def test_a_busy_app_refuses_a_second_action(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        notes = _spy_notify(app)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app.busy = True
            app.do_switch("work")
            assert notes == [("another action is still running", {"severity": "warning"})]

    async def test_an_unknown_target_surfaces_as_an_error(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        notes = _spy_notify(app)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app.do_switch("ghost")
            await settle_workers(pilot)
            assert notes[-1][0].startswith("switch failed:")
            assert notes[-1][1] == {"severity": "error", "timeout": 8}
            assert app.busy is False

    async def test_a_failed_best_pick_reports_the_same_error(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path, switch=_RaisingSwitch())  # type: ignore[arg-type]
        notes = _spy_notify(app)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_switch(pilot)
            await pilot.press("b")
            await settle_workers(pilot)
            assert notes[-1][0] == "switch failed: boom"
            assert notes[-1][1] == {"severity": "error", "timeout": 8}
            assert app.busy is False


class TestLiveUpdates:
    async def test_a_refresh_updates_rows_in_place(self, tmp_path: Path) -> None:
        app, _api, _store, clock = wired_app(tmp_path, active_name="work")
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_switch(pilot)
            items = list(app.screen.query(AccountItem))
            clock.advance(700)  # past TTL + poll plans — the snapshot differs
            app.request_refresh()
            await settle_workers(pilot)
            # Same membership → same ListItem objects repainted, not rebuilt.
            assert list(app.screen.query(AccountItem)) == items
            assert _list(app).index == 0
            assert any(item.has_class("flash") for item in items)  # the pass ran

    async def test_a_member_change_preserves_the_cursor_when_it_fits(self, tmp_path: Path) -> None:
        app, _api, store, _clock = wired_app(tmp_path, names=("work", "personal", "alt"))
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_switch(pilot)
            _list(app).index = 1
            store.remove(AccountName("alt"))
            app.request_refresh()
            await settle_workers(pilot)
            assert _names(app) == ["work", "personal"]
            assert _list(app).index == 1

    async def test_a_member_change_rebuilds_and_clamps_the_cursor(self, tmp_path: Path) -> None:
        app, _api, store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_switch(pilot)
            _list(app).index = 1
            store.remove(AccountName("personal"))
            app.request_refresh()
            await settle_workers(pilot)
            assert _names(app) == ["work"]
            assert _list(app).index == 0

    async def test_a_fresh_measurement_flashes_the_row(self, tmp_path: Path) -> None:
        app, _api, _store, clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_switch(pilot)
            clock.advance(700)  # past TTL and the longest poll-plan interval
            app.request_refresh()
            await settle_workers(pilot)
            assert _flashed(app) == ["work", "personal"]  # both rows re-measured

    async def test_only_newly_measured_rows_flash(self, tmp_path: Path) -> None:
        # work's plan isn't due at +700 — only personal refetches and flashes
        cache = InMemoryUsageCache()
        now = 1_000_000.0
        entry = replace(_seeded_entry(10.0, now), next_poll_at_s=now + 3600)
        cache.save("work", entry)
        app, _api, _store, clock = wired_app(tmp_path, usage_cache=cache)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_switch(pilot)
            clock.advance(700)
            app.request_refresh()
            await settle_workers(pilot)
            assert _flashed(app) == ["personal"]

    async def test_the_flash_clears_after_its_timer(self, tmp_path: Path) -> None:
        app, _api, _store, clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_switch(pilot)
            clock.advance(700)
            app.request_refresh()
            await settle_workers(pilot)
            assert _flashed(app) == ["work", "personal"]
            await pilot.pause(FLASH_S + 0.5)
            assert _flashed(app) == []

    async def test_a_lit_row_is_not_re_armed_on_the_next_refresh(self, tmp_path: Path) -> None:
        app, _api, _store, clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_switch(pilot)
            screen = app.screen
            original_set_timer = screen.set_timer
            calls = 0

            def counting(delay: float, callback: object = None, **kw: object) -> object:
                nonlocal calls
                calls += 1
                return original_set_timer(delay, callback, **kw)

            screen.set_timer = counting  # type: ignore[method-assign]
            clock.advance(700)
            app.request_refresh()
            await settle_workers(pilot)
            assert calls == 2
            clock.advance(700)  # next poll plan due again — stamps move
            app.request_refresh()
            await settle_workers(pilot)
            # Still inside FLASH_S → already-lit rows keep their first timer.
            assert calls == 2
