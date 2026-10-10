"""The dashboard's nested action menu — structure, navigation, dispatch.

Everything below ``#menu-title``/``#menu`` is exercised through Pilot key
presses: the menu owns the cursor, Enter selects, Esc/left walks the stack
back. Entries whose targets arrive in later tasks announce themselves
through a notification instead of dead-ending.
"""

import threading
from pathlib import Path

from support.in_memory_settings import InMemorySettings, emails_visible_settings
from support.tui_app import settle_workers, wired_app
from textual.widgets import ListView, Static

from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.tui.account_list import WatchScreen
from claude_acc_manager.tui.app import CamApp
from claude_acc_manager.tui.autoview import AutoScreen
from claude_acc_manager.tui.dashboard import DashboardScreen
from claude_acc_manager.tui.modals import ConfirmModal
from claude_acc_manager.tui.widgets import AccountCard, AccountsPanel, MenuItem

ROOT_LABELS = [
    "s  Switch account…",
    "w  Watch accounts",
    "g  Auto-switch view",
    "e  Enable / disable account…",
    "r  Remove account…",
    "t  Theme…",
    "c  Settings…",
    "q  Quit",
]


def _menu(app: CamApp) -> ListView:
    """The dashboard's menu list widget."""
    return app.screen.query_one("#menu", ListView)


def _labels(app: CamApp) -> list[str]:
    """The rendered label of every row in the menu list."""
    return [str(item.query_one(Static).content) for item in app.screen.query(MenuItem)]


def _crumb(app: CamApp) -> str:
    """The breadcrumb title above the menu ("menu › theme")."""
    return str(app.screen.query_one("#menu-title", Static).content)


async def _select(pilot, index: int) -> None:
    """Move the menu cursor to *index* and press Enter."""
    _menu(pilot.app).index = index
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()


class TestMenuStructure:
    async def test_the_root_menu_renders_focused_with_a_crumb(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            assert _menu(app).has_focus
            assert _crumb(app) == "menu"
            assert _labels(app) == ROOT_LABELS
            app.screen.query_one("#accounts-panel")

    async def test_j_and_k_move_the_cursor(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await pilot.press("j")
            assert _menu(app).index == 1
            await pilot.press("j")
            assert _menu(app).index == 2
            await pilot.press("k")
            assert _menu(app).index == 1

    async def test_a_submenu_push_resets_the_cursor(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _select(pilot, 3)  # Enable / disable account…
            assert _crumb(app) == "menu › enable / disable"
            assert _menu(app).index == 0


class TestWatchAndQuit:
    async def test_the_auto_entry_stacks_the_dry_run_preview(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _select(pilot, 2)  # Auto-switch view
            assert isinstance(app.screen, AutoScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, DashboardScreen)

    async def test_watch_opens_the_monitor_and_esc_returns(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _select(pilot, 1)  # Watch accounts
            assert isinstance(app.screen, WatchScreen)
            app.screen.query_one("#accounts")
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, DashboardScreen)

    async def test_the_w_binding_pushes_watch_once(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await pilot.press("w")
            assert isinstance(app.screen, WatchScreen)
            depth = len(app.screen_stack)
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("w")
            assert isinstance(app.screen, WatchScreen)
            assert len(app.screen_stack) == depth  # never stacks twice

    async def test_quit_exits_the_app(self, tmp_path: Path) -> None:
        exits: list[bool] = []
        app, _api, _store, _clock = wired_app(tmp_path)
        app.exit = lambda *a, **kw: exits.append(True)  # type: ignore[method-assign]
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _select(pilot, 7)  # Quit
            assert exits == [True]


class TestThemeSubmenu:
    async def test_theme_marks_the_current_and_applies_on_select(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _select(pilot, 5)  # Theme…
            assert _crumb(app) == "menu › theme"
            assert _labels(app) == ["d  ● dark", "l    light", "← back"]
            back = app.screen.query(MenuItem).last()
            assert back.query_one(Static).has_class("menu-item-muted")
            await _select(pilot, 1)  # light
            assert app.theme == "cam-light"
            assert app.theme_name == "light"
            assert _crumb(app) == "menu"

    async def test_theme_reflects_the_active_one(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app.apply_theme("light")
            await _select(pilot, 5)
            assert _labels(app) == ["d    dark", "l  ● light", "← back"]


class TestNavigationBack:
    async def test_escape_pops_the_submenu(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _select(pilot, 5)
            await pilot.press("escape")
            await pilot.pause()
            assert _crumb(app) == "menu"
            assert _labels(app) == ROOT_LABELS

    async def test_left_arrow_also_backs_out(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _select(pilot, 5)
            await pilot.press("left")
            await pilot.pause()
            assert _crumb(app) == "menu"

    async def test_escape_at_root_is_a_noop(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await pilot.press("escape")
            await pilot.pause()
            assert _crumb(app) == "menu"
            assert isinstance(app.screen, DashboardScreen)

    async def test_the_back_row_returns_to_root(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _select(pilot, 5)
            await _select(pilot, 2)  # ← back
            assert _crumb(app) == "menu"


class TestAccountSubmenus:
    async def test_disable_lists_every_account_with_its_next_state(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(
            tmp_path, active_name="work", settings=emails_visible_settings(tmp_path)
        )
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _select(pilot, 3)
            assert _crumb(app) == "menu › enable / disable"
            assert _labels(app) == [
                "1  work (work@example.com)   → disable",
                "2  personal (personal@example.com)   → disable",
                "← back",
            ]

    async def test_a_disabled_account_offers_enable(self, tmp_path: Path) -> None:
        app, _api, store, _clock = wired_app(tmp_path, settings=emails_visible_settings(tmp_path))
        store.set_enabled(AccountName("work"), False)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _select(pilot, 3)
            assert _labels(app)[0] == "1  work (work@example.com)  (disabled)   → enable"

    async def test_remove_lists_every_account(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path, settings=emails_visible_settings(tmp_path))
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _select(pilot, 4)  # Remove account…
            assert _crumb(app) == "menu › remove account"
            assert _labels(app) == [
                "1  work (work@example.com)",
                "2  personal (personal@example.com)",
                "← back",
            ]

    async def test_emails_stay_hidden_until_p_shows_them(self, tmp_path: Path) -> None:
        # arrange — no seed: privacy.redactEmails defaults to hidden
        settings = InMemorySettings(tmp_path)
        app, _api, _store, _clock = wired_app(tmp_path, settings=settings)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _select(pilot, 4)
            assert _labels(app) == ["1  work", "2  personal", "← back"]
            # act — the p key flips the app reactive and repaints the open menu
            await pilot.press("p")
            await pilot.pause()
            assert _labels(app) == [
                "1  work (work@example.com)",
                "2  personal (personal@example.com)",
                "← back",
            ]
            # assert — the choice persisted through the settings use case
            assert settings._values["privacy.redactEmails"] is False

    async def test_p_a_second_time_hides_again(self, tmp_path: Path) -> None:
        settings = InMemorySettings(tmp_path)
        app, _api, _store, _clock = wired_app(tmp_path, settings=settings)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _select(pilot, 4)
            await pilot.press("p")
            await pilot.pause()
            await pilot.press("p")
            await pilot.pause()
            assert _labels(app) == ["1  work", "2  personal", "← back"]
            assert settings._values["privacy.redactEmails"] is True

    async def test_p_reports_the_new_visibility(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        notes = _spy_notify(app)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await pilot.press("p")
            await pilot.pause()
            await pilot.press("p")
            await pilot.pause()
            assert notes == [("Emails: shown", {}), ("Emails: hidden", {})]

    async def test_p_rebuilds_the_toggle_submenu(self, tmp_path: Path) -> None:
        # the enable/disable rows bake ``name (email)`` — a mid-submenu flip
        # must re-run the builder, not just repaint the cached rows
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _select(pilot, 3)  # Enable / disable account…
            assert _labels(app) == [
                "1  work   → disable",
                "2  personal   → disable",
                "← back",
            ]
            await pilot.press("p")
            await pilot.pause()
            assert _labels(app) == [
                "1  work (work@example.com)   → disable",
                "2  personal (personal@example.com)   → disable",
                "← back",
            ]

    async def test_the_submenus_survive_a_missing_snapshot(self, tmp_path: Path) -> None:
        # arrange — the collect worker is parked, so snapshot stays None:
        # opening an account submenu must list just the back row, not crash
        gate = threading.Event()
        app, _api, _store, _clock = wired_app(tmp_path, collect_gate=gate)
        async with app.run_test() as pilot:
            await pilot.pause()
            await _select(pilot, 3)  # Enable / disable account…
            assert _labels(app) == ["← back"]
            await _select(pilot, 0)  # ← back
            await _select(pilot, 4)  # Remove account…
            assert _labels(app) == ["← back"]
            gate.set()
            await settle_workers(pilot)


def _spy_notify(app: CamApp) -> list[tuple[str, dict[str, object]]]:
    """Record ``notify`` calls as ``(message, kwargs)`` pairs."""
    calls: list[tuple[str, dict[str, object]]] = []
    app.notify = lambda message, **kw: calls.append((message, kw))  # type: ignore[method-assign]
    return calls


class TestLeafDispatch:
    """Account-targeted leaves run their action and settle the menu."""

    async def test_a_disable_leaf_flips_the_account(self, tmp_path: Path) -> None:
        app, _api, store, _clock = wired_app(tmp_path)
        notes = _spy_notify(app)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _select(pilot, 3)
            await _select(pilot, 0)  # work → disable
            await settle_workers(pilot)
            account = store.get(AccountName("work"))
            assert account is not None and account.enabled is False
            assert _crumb(app) == "menu"  # the submenu popped under the toast
            assert ("disabled account 'work'", {"severity": "information"}) in notes

    async def test_a_remove_leaf_asks_for_confirmation(self, tmp_path: Path) -> None:
        app, _api, store, _clock = wired_app(tmp_path, settings=emails_visible_settings(tmp_path))
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _select(pilot, 4)
            await _select(pilot, 0)
            assert isinstance(app.screen, ConfirmModal)
            body = str(app.screen.query_one(".modal-body", Static).content)
            assert body.startswith("Remove account 'work' (work@example.com)?")
            await pilot.press("escape")
            await pilot.pause()
            # the submenu was already popped under the modal — root is back
            assert isinstance(app.screen, DashboardScreen)
            assert _crumb(app) == "menu"


class TestMenuAccelerators:
    """Each row answers to its printed accelerator key."""

    async def test_a_root_key_opens_its_submenu(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await pilot.press("e")
            await pilot.pause()
            assert _crumb(app) == "menu › enable / disable"

    async def test_a_bound_key_stays_with_its_binding(self, tmp_path: Path) -> None:
        # 'w' is a row accelerator AND the open_watch binding — one outcome
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await pilot.press("w")
            await pilot.pause()
            assert isinstance(app.screen, WatchScreen)

    async def test_a_digit_key_runs_its_account_row(self, tmp_path: Path) -> None:
        app, _api, store, _clock = wired_app(tmp_path)
        notes = _spy_notify(app)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await pilot.press("e")
            await pilot.press("2")
            await settle_workers(pilot)
            account = store.get(AccountName("personal"))
            assert account is not None and account.enabled is False
            assert ("disabled account 'personal'", {"severity": "information"}) in notes

    async def test_theme_rows_take_letter_keys(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await pilot.press("t")
            await pilot.pause()
            assert _crumb(app) == "menu › theme"
            await pilot.press("l")
            await pilot.pause()
            assert app.theme_name == "light"
            assert _crumb(app) == "menu"

    async def test_digit_keys_spill_to_letters_past_nine(self, tmp_path: Path) -> None:
        names = tuple(f"acc{i}" for i in range(16))
        app, _api, _store, _clock = wired_app(tmp_path, names=names)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await pilot.press("r")
            await pilot.pause()
            labels = _labels(app)
            assert [label.split()[0] for label in labels[:-1]] == [str(i) for i in range(1, 10)] + [
                "a",
                "b",
                "c",
                "d",
                "e",
                "f",
                "acc15",
            ]
            assert labels[-1] == "← back"
            await pilot.press("b")  # acc10's key — the modal asks to confirm
            await pilot.pause()
            assert isinstance(app.screen, ConfirmModal)
            body = str(app.screen.query_one(".modal-body", Static).content)
            assert "'acc10'" in body
            await pilot.press("escape")

    async def test_an_unmatched_key_does_not_swallow_bindings(self, tmp_path: Path) -> None:
        # 'z' names no row and no binding — the press is inert, not an error
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await pilot.press("z")
            await pilot.pause()
            assert _crumb(app) == "menu"
            await pilot.press("j")
            assert _menu(app).index == 1


class TestAllowSelect:
    """Chrome refuses text selection; account content keeps it."""

    async def test_menu_chrome_is_not_selectable(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            assert app.screen.query_one("#menu-title", Static).allow_select is False
            for item in app.screen.query(MenuItem):
                assert item.allow_select is False
                assert item.query_one(Static).allow_select is False

    async def test_modal_chrome_is_not_selectable(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _select(pilot, 4)
            await _select(pilot, 0)
            modal = app.screen
            assert isinstance(modal, ConfirmModal)
            assert all(not static.allow_select for static in modal.query(Static))

    async def test_screen_chrome_is_not_selectable(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await pilot.press("w")
            await settle_workers(pilot)
            assert app.screen.query_one("#list-title", Static).allow_select is False
            await pilot.press("escape")
            await pilot.press("g")
            await settle_workers(pilot)
            assert isinstance(app.screen, AutoScreen)
            assert app.screen.query_one("#mode-badge", Static).allow_select is False

    async def test_account_content_stays_selectable(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            assert app.screen.query_one(AccountsPanel).allow_select is True
            await pilot.press("w")
            await settle_workers(pilot)
            assert isinstance(app.screen, WatchScreen)
            for card in app.screen.query(AccountCard):
                assert card.allow_select is True
            # the summary/candidates on the auto view are content too
            await pilot.press("escape")
            await pilot.press("g")
            await settle_workers(pilot)
            assert app.screen.query_one("#auto-summary", Static).allow_select is True
            assert app.screen.query_one("#candidates", Static).allow_select is True
