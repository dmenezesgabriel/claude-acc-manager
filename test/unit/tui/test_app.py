"""CamApp Pilot tests — the poll loop over the shared UseCases surface.

All port I/O happens inside thread workers; ``settle_workers`` drains them
so each assertion sees a fully-applied snapshot. The app's clock is the
injected ``usage_clock``, so staleness notes are deterministic under
ControllableClock.
"""

import asyncio
import threading
from pathlib import Path

from support.fake_token_refresher import FakeTokenRefresher
from support.in_memory_settings import emails_visible_settings
from support.rich_asserts import visual_plain
from support.tui_app import settle_workers, wired_app
from support.use_cases import make_use_cases
from textual.widgets import Button, Footer, Static

from claude_acc_manager.accounts.application.use_cases.collect_accounts_view import (
    AccountsView,
    CollectAccountsView,
)
from claude_acc_manager.accounts.domain.entities import QuarantineEntry
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.tui.account_list import WatchScreen
from claude_acc_manager.tui.app import CamApp
from claude_acc_manager.tui.dashboard import DashboardScreen
from claude_acc_manager.tui.modals import ConfirmModal
from claude_acc_manager.tui.widgets import AccountItem
from claude_acc_manager.usage.application.ports import AnthropicApiError
from claude_acc_manager.usage.application.use_cases.fetch_account_usage import (
    FetchAccountUsage,
    UsageReport,
)


class _RaisingFetchUsage(FetchAccountUsage):
    """Fails every fetch — exercises the refresh worker's error path."""

    def __init__(self) -> None:
        """No ports needed — execute raises before it can reach them."""

    def execute(self, account_key: str, is_active: bool) -> UsageReport:
        """Raise unconditionally."""
        raise RuntimeError("boom")


class _RecordingFetchUsage(FetchAccountUsage):
    """Records the (name, is_active) each fetch call received."""

    def __init__(self) -> None:
        """Start with no calls recorded; no ports are needed."""
        self.calls: list[tuple[str, bool]] = []

    def execute(self, account_key: str, is_active: bool) -> UsageReport:
        """Record the call; report 'unavailable' without touching ports."""
        self.calls.append((account_key, is_active))
        return UsageReport(
            snapshot=None, stale=True, last_error="skipped", permanent_auth_error=False
        )


class _BlockingCollectAccountsView(CollectAccountsView):
    """Holds the refresh worker mid-flight until the test releases it."""

    def __init__(self, view: AccountsView) -> None:
        """Pin the view returned once released."""
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self._view = view

    def execute(self) -> AccountsView:
        """Signal entry, wait for release, return the pinned view."""
        self.calls += 1
        self.entered.set()
        self.release.wait(timeout=5)
        return self._view


class TestDefaults:
    def test_the_app_starts_idle_on_the_dashboard(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        # the kwarg-free constructor is the `cam tui` default
        assert CamApp(make_use_cases(tmp_path))._start == "dashboard"
        assert app._start == "dashboard"
        assert app._refreshing is False
        assert app._refresh_started_at is None
        assert app._refresh_generation == 0
        assert app._applied_generation == 0
        assert app._last_refresh_error == ""
        assert app.theme_name == "dark"
        assert app.threshold_pct == 90.0
        assert app.snapshot is None
        assert app.refresh_status == ""
        assert app.busy is False

    def test_the_pre_snapshot_window_reads_as_empty(self, tmp_path: Path) -> None:
        # arrange — the app is wired but no poll has landed yet
        app, _api, _store, _clock = wired_app(tmp_path)

        # act / assert — snapshot consumers degrade to empty, not AttributeError
        assert app.headroom_map() == {}
        assert app._snapshot_row("work") is None


class TestPollLoop:
    """The 3s tick: collect → gated fetch pass → re-collect → apply."""

    async def test_mount_collects_every_registered_account(self, tmp_path: Path) -> None:
        notes: list[tuple[object, dict[str, object]]] = []
        app, _api, _store, _clock = wired_app(tmp_path)
        app.notify = lambda message, **kw: notes.append((message, kw))
        # wide: below 100 cols the breakpoint collapses the mini rows
        async with app.run_test(size=(120, 24)) as pilot:
            await settle_workers(pilot)
            assert isinstance(app.screen, DashboardScreen)
            panel = app.screen.query_one("#accounts-panel")
            rendered = visual_plain(panel.render(), 120)
            assert "work" in rendered
            assert "personal" in rendered
            assert app.screen.query_one(Footer)
            assert app.snapshot is not None
            assert app._refreshing is False
            assert app._refresh_started_at is None
            assert app._last_refresh_error == ""
            assert [r.account.name.value for r in app.snapshot.accounts] == [
                "work",
                "personal",
            ]
            # a successful pass never notifies — only failures surface
            assert notes == []

    async def test_due_accounts_are_fetched_once(self, tmp_path: Path) -> None:
        app, api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            assert len(api.requests) == 2
            assert app._refresh_generation == 1
            assert app._applied_generation == 1

    async def test_a_gated_tick_serves_the_cache(self, tmp_path: Path) -> None:
        # the poller cannot storm the endpoint: a second tick right after a
        # successful fetch finds every entry fresh and hits nothing
        app, api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app.request_refresh()
            await settle_workers(pilot)
            assert len(api.requests) == 2
            assert app._refresh_generation == 2

    async def test_quarantined_rows_are_never_polled(self, tmp_path: Path) -> None:
        fetcher = _RecordingFetchUsage()
        app, _api, store, _clock = wired_app(tmp_path, fetch_usage=fetcher)
        store.set_quarantined(QuarantineEntry("work", "permanent_auth_error", "t", "sha256:x"))
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            assert fetcher.calls == [("personal", False)]

    async def test_is_active_is_passed_through_to_the_fetch(self, tmp_path: Path) -> None:
        fetcher = _RecordingFetchUsage()
        app, _api, _store, _clock = wired_app(tmp_path, fetch_usage=fetcher, active_name="work")
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            assert fetcher.calls == [("work", True), ("personal", False)]

    async def test_permanent_auth_error_writes_a_tombstone(self, tmp_path: Path) -> None:
        # an expired parked token is refreshed; the provider answers
        # invalid_grant and the poller tombstones the dead lineage itself
        app, _api, store, _clock = wired_app(
            tmp_path,
            names=("work",),
            refresher=FakeTokenRefresher(error=AnthropicApiError(400, "invalid_grant")),
            expired_credentials=True,
        )
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            assert [entry.name for entry in store.quarantined()] == ["work"]

    async def test_a_second_tick_is_dropped_while_refreshing(self, tmp_path: Path) -> None:
        view = AccountsView(active_name=None, live_identity=None, accounts=(), taken_at_s=0.0)
        blocking = _BlockingCollectAccountsView(view)
        app, _api, _store, _clock = wired_app(tmp_path, collect_view=blocking)
        async with app.run_test() as pilot:
            assert await asyncio.to_thread(blocking.entered.wait, 5)
            assert app._refreshing is True
            assert app._refresh_started_at is not None
            workers = list(app.workers)
            assert len(workers) == 1
            assert workers[0].name == "snapshot-refresh"
            assert workers[0].exit_on_error is False
            app.request_refresh()
            assert app._refresh_generation == 1
            blocking.release.set()
            await settle_workers(pilot)
            assert app._refreshing is False
            assert app._refresh_generation == 1

    async def test_the_poll_interval_ticks_again(self, tmp_path: Path) -> None:
        view = AccountsView(active_name=None, live_identity=None, accounts=(), taken_at_s=0.0)
        counting = _BlockingCollectAccountsView(view)
        counting.release.set()  # never hold — count invocations only
        app, _api, _store, _clock = wired_app(tmp_path, collect_view=counting)
        app.POLL_INTERVAL_S = 0.05
        async with app.run_test():
            for _ in range(40):
                await asyncio.sleep(0.05)
                if counting.calls >= 4:  # two ticks × two collects each
                    break
            assert counting.calls >= 4

    async def test_the_status_timer_ages_the_note(self, tmp_path: Path) -> None:
        # the 1s status timer is the only updater once the poll lane is
        # parked — poll for it inside the window before a mutant's slower
        # interval could fire
        app, _api, _store, clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            clock.advance(61)
            for _ in range(35):
                await asyncio.sleep(0.05)
                if app.refresh_status:
                    break
            assert app.refresh_status == "snapshot 1m ago"


class TestSnapshotGuard:
    async def test_an_older_worker_result_is_dropped(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            applied = app.snapshot
            stale = AccountsView(active_name=None, live_identity=None, accounts=(), taken_at_s=1.0)
            app._apply_snapshot(0, stale)
            assert app.snapshot is applied

    async def test_the_current_generation_replaces_the_snapshot(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            fresh = AccountsView(active_name=None, live_identity=None, accounts=(), taken_at_s=2.0)
            app._apply_snapshot(app._applied_generation, fresh)
            assert app.snapshot is fresh


class TestRefreshStatus:
    async def test_stale_snapshot_age_is_surfaced(self, tmp_path: Path) -> None:
        app, _api, _store, clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            clock.advance(61)
            app._update_refresh_status()
            assert app.refresh_status == "snapshot 1m ago"

    async def test_the_age_floor_is_inclusive(self, tmp_path: Path) -> None:
        app, _api, _store, clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            clock.advance(60)
            app._update_refresh_status()
            assert app.refresh_status == "snapshot 1m ago"

    async def test_refreshing_note_reports_elapsed(self, tmp_path: Path) -> None:
        app, _api, _store, clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app._refreshing = True
            app._refresh_started_at = clock.now_epoch_s() - app.POLL_INTERVAL_S
            app._update_refresh_status()
            assert "refreshing 1h" in app.refresh_status

    async def test_no_refreshing_note_once_the_lane_clears(self, tmp_path: Path) -> None:
        app, _api, _store, clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app._refreshing = False
            app._refresh_started_at = clock.now_epoch_s() - app.POLL_INTERVAL_S - 1
            app._update_refresh_status()
            assert "refreshing" not in app.refresh_status

    async def test_age_and_refresh_notes_join(self, tmp_path: Path) -> None:
        app, _api, _store, clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            clock.advance(120)
            app._refreshing = True
            app._refresh_started_at = clock.now_epoch_s() - app.POLL_INTERVAL_S
            app._update_refresh_status()
            assert app.refresh_status == "snapshot 2m ago · refreshing 1h"


class TestManualRefresh:
    async def test_f_requests_a_pass_now(self, tmp_path: Path) -> None:
        notes: list[tuple[object, dict[str, object]]] = []
        app, api, _store, _clock = wired_app(tmp_path)
        app.notify = lambda message, **kw: notes.append((message, kw))
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await pilot.press("f")
            await settle_workers(pilot)
            assert app._refresh_generation == 2
            assert notes == [("Refreshing usage…", {"timeout": 2})]


class TestThemeToggle:
    async def test_ctrl_t_cycles_dark_light(self, tmp_path: Path) -> None:
        notes: list[tuple[object, dict[str, object]]] = []
        app, _api, _store, _clock = wired_app(tmp_path)
        app.notify = lambda message, **kw: notes.append((message, kw))
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            assert app.theme == "cam-dark"
            await pilot.press("ctrl+t")
            assert app.theme == "cam-light"
            await pilot.press("ctrl+t")
            assert app.theme == "cam-dark"
            assert [n[0] for n in notes] == ["Theme: light", "Theme: dark"]


class TestWatchStart:
    async def test_watch_stacks_over_the_dashboard(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path, start="watch")
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            assert isinstance(app.screen, WatchScreen)
            assert [item.account_name.value for item in app.screen.query(AccountItem)] == [
                "work",
                "personal",
            ]
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, DashboardScreen)


class TestAccountActions:
    """Toggle/remove share the switch lane: busy-gated, off-thread, toasts."""

    async def test_toggle_disables_the_named_account(self, tmp_path: Path) -> None:
        notes: list[tuple[object, dict[str, object]]] = []
        captured: list[dict[str, object]] = []
        app, _api, store, _clock = wired_app(tmp_path)
        app.notify = lambda message, **kw: notes.append((message, kw))
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            original = app.run_worker
            app.run_worker = lambda work, **kw: (  # type: ignore[method-assign]
                captured.append(kw),
                original(work, **kw),
            )[1]
            app.do_toggle_enabled("personal")
            await settle_workers(pilot)
            action_kwargs = [kw for kw in captured if kw["group"] == "action"]
            assert [kw["name"] for kw in action_kwargs] == ["action"]
            # the label moved from the name kwarg to the auto-built description
            assert "toggle personal" in action_kwargs[0]["description"]
            account = store.get(AccountName("personal"))
            assert account is not None and account.enabled is False
            assert notes == [("disabled account 'personal'", {"severity": "information"})]
            assert app.busy is False

    async def test_toggle_re_enables_a_disabled_account(self, tmp_path: Path) -> None:
        notes: list[tuple[object, dict[str, object]]] = []
        app, _api, store, _clock = wired_app(tmp_path)
        store.set_enabled(AccountName("personal"), False)
        app.notify = lambda message, **kw: notes.append((message, kw))
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app.do_toggle_enabled("personal")
            await settle_workers(pilot)
            account = store.get(AccountName("personal"))
            assert account is not None and account.enabled is True
            assert notes == [("enabled account 'personal'", {"severity": "information"})]

    async def test_toggle_an_unknown_account_warns_without_a_worker(self, tmp_path: Path) -> None:
        notes: list[tuple[object, dict[str, object]]] = []
        app, _api, _store, _clock = wired_app(tmp_path)
        app.notify = lambda message, **kw: notes.append((message, kw))
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app.do_toggle_enabled("ghost")
            await pilot.pause()
            assert notes == [("no account named 'ghost'", {"severity": "warning"})]
            assert app.busy is False

    async def test_a_failed_toggle_surfaces_the_error(self, tmp_path: Path) -> None:
        # a stale snapshot can name an account the store no longer has —
        # set_enabled raises KeyError and the lane reports it
        notes: list[tuple[object, dict[str, object]]] = []
        app, _api, store, _clock = wired_app(tmp_path)
        app.notify = lambda message, **kw: notes.append((message, kw))
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            store.remove(AccountName("personal"))
            app.do_toggle_enabled("personal")  # the row is still in the snapshot
            await settle_workers(pilot)
            assert notes == [("toggle failed: 'personal'", {"severity": "error", "timeout": 8})]

    async def test_remove_drops_the_account(self, tmp_path: Path) -> None:
        notes: list[tuple[object, dict[str, object]]] = []
        captured: list[dict[str, object]] = []
        app, _api, store, _clock = wired_app(tmp_path)
        app.notify = lambda message, **kw: notes.append((message, kw))
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            original = app.run_worker
            app.run_worker = lambda work, **kw: (  # type: ignore[method-assign]
                captured.append(kw),
                original(work, **kw),
            )[1]
            app.do_remove("personal")
            await settle_workers(pilot)
            action_kwargs = [kw for kw in captured if kw["group"] == "action"]
            assert [kw["name"] for kw in action_kwargs] == ["action"]
            # the label moved from the name kwarg to the auto-built description
            assert "remove personal" in action_kwargs[0]["description"]
            assert store.get(AccountName("personal")) is None
            assert notes == [("removed account 'personal'", {"severity": "information"})]

    async def test_a_failed_remove_surfaces_the_error(self, tmp_path: Path) -> None:
        notes: list[tuple[object, dict[str, object]]] = []
        app, _api, _store, _clock = wired_app(tmp_path)
        app.notify = lambda message, **kw: notes.append((message, kw))
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app.do_remove("ghost")
            await settle_workers(pilot)
            assert notes == [("remove failed: 'ghost'", {"severity": "error", "timeout": 8})]

    async def test_confirm_remove_only_runs_on_yes(self, tmp_path: Path) -> None:
        app, _api, store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app.confirm_remove("personal")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmModal)
            await pilot.press("n")
            await pilot.pause()
            assert store.get(AccountName("personal")) is not None
            app.confirm_remove("personal")
            await pilot.pause()
            await pilot.press("y")
            await settle_workers(pilot)
            assert store.get(AccountName("personal")) is None

    async def test_the_remove_prompt_names_and_warns_on_active(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(
            tmp_path, active_name="work", settings=emails_visible_settings(tmp_path)
        )
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app.confirm_remove("work")
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, ConfirmModal)
            title = str(modal.query_one(".modal-title", Static).content)
            body = str(modal.query_one(".modal-body", Static).content)
            assert title == "Remove account"
            assert str(modal.query_one("#yes", Button).label) == "Remove"
            assert body == (
                "Remove account 'work' (work@example.com)?\n\n"
                "Its stored login directory is deleted.\n"
                "'work' is the live account — the login stays, unmanaged."
            )

    async def test_the_remove_prompt_hides_the_email_by_default(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path, active_name="work")
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app.confirm_remove("work")
            await pilot.pause()
            body = str(app.screen.query_one(".modal-body", Static).content)
            assert body.startswith("Remove account 'work'?")
            assert "example.com" not in body

    async def test_the_remove_prompt_stays_plain_for_others(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(
            tmp_path, active_name="work", settings=emails_visible_settings(tmp_path)
        )
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app.confirm_remove("personal")
            await pilot.pause()
            body = str(app.screen.query_one(".modal-body", Static).content)
            assert body == (
                "Remove account 'personal' (personal@example.com)?\n\n"
                "Its stored login directory is deleted."
            )
            assert "unmanaged" not in body

    async def test_confirm_remove_of_a_ghost_has_no_extras(self, tmp_path: Path) -> None:
        # dispatch feeds a snapshot row, but the method itself must not
        # crash on a name the snapshot doesn't know
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app.confirm_remove("ghost")
            await pilot.pause()
            body = str(app.screen.query_one(".modal-body", Static).content)
            assert body == "Remove account 'ghost'?\n\nIts stored login directory is deleted."


class TestWorkerFailure:
    async def test_a_failed_refresh_clears_the_lane_and_warns_once(self, tmp_path: Path) -> None:
        notes: list[tuple[object, dict[str, object]]] = []
        app, _api, _store, _clock = wired_app(tmp_path, fetch_usage=_RaisingFetchUsage())
        app.notify = lambda message, **kw: notes.append((message, kw))
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            assert app.snapshot is None
            assert app._refreshing is False
            assert app._refresh_started_at is None
            assert app._last_refresh_error == "boom"
            assert notes == [("Refresh failed: boom", {"severity": "warning", "timeout": 6})]
            # a repeat of the same failure does not notify again
            app.request_refresh()
            await settle_workers(pilot)
            assert app._refreshing is False
            assert len(notes) == 1
