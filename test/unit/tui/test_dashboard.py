"""The dashboard's nested action menu — structure, navigation, dispatch.

Everything below ``#menu-title``/``#menu`` is exercised through Pilot key
presses: the menu owns the cursor, Enter selects, Esc/left walks the stack
back. Entries whose targets arrive in later tasks announce themselves
through a notification instead of dead-ending.
"""

from pathlib import Path

from support.tui_app import settle_workers, wired_app
from textual.widgets import ListView, Static

from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.tui.account_list import WatchScreen
from claude_acc_manager.tui.app import CamApp
from claude_acc_manager.tui.dashboard import DashboardScreen
from claude_acc_manager.tui.widgets import MenuItem

ROOT_LABELS = [
    "Switch account…",
    "Watch accounts",
    "Auto-switch view",
    "Enable / disable account…",
    "Remove account…",
    "Theme…",
    "Quit",
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
            await _select(pilot, 6)  # Quit
            assert exits == [True]


class TestThemeSubmenu:
    async def test_theme_marks_the_current_and_applies_on_select(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _select(pilot, 5)  # Theme…
            assert _crumb(app) == "menu › theme"
            assert _labels(app) == ["● dark", "  light", "← back"]
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
            assert _labels(app) == ["  dark", "● light", "← back"]


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
        app, _api, _store, _clock = wired_app(tmp_path, active_name="work")
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _select(pilot, 3)
            assert _crumb(app) == "menu › enable / disable"
            assert _labels(app) == [
                "work (work@example.com)   → disable",
                "personal (personal@example.com)   → disable",
                "← back",
            ]

    async def test_a_disabled_account_offers_enable(self, tmp_path: Path) -> None:
        app, _api, store, _clock = wired_app(tmp_path)
        store.set_enabled(AccountName("work"), False)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _select(pilot, 3)
            assert _labels(app)[0] == "work (work@example.com)  (disabled)   → enable"

    async def test_remove_lists_every_account(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _select(pilot, 4)  # Remove account…
            assert _crumb(app) == "menu › remove account"
            assert _labels(app) == [
                "work (work@example.com)",
                "personal (personal@example.com)",
                "← back",
            ]


def _spy_notify(app: CamApp) -> list[tuple[str, dict[str, object]]]:
    """Record ``notify`` calls as ``(message, kwargs)`` pairs."""
    calls: list[tuple[str, dict[str, object]]] = []
    app.notify = lambda message, **kw: calls.append((message, kw))  # type: ignore[method-assign]
    return calls


class TestPendingDispatch:
    """Entries whose targets land in T11/T12 announce instead of dead-end."""

    async def test_auto_announces_it_is_pending(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        notes = _spy_notify(app)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _select(pilot, 2)  # Auto-switch view
            assert notes == [
                (
                    "auto: not wired yet — lands with a later task",
                    {"severity": "warning", "timeout": 4},
                )
            ]

    async def test_a_disable_leaf_announces_it_is_pending(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        notes = _spy_notify(app)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _select(pilot, 3)
            await _select(pilot, 0)  # first account row
            assert notes == [
                (
                    "disable:work: not wired yet — lands with a later task",
                    {"severity": "warning", "timeout": 4},
                )
            ]

    async def test_a_remove_leaf_announces_it_is_pending(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        notes = _spy_notify(app)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _select(pilot, 4)
            await _select(pilot, 0)
            assert notes == [
                (
                    "remove:work: not wired yet — lands with a later task",
                    {"severity": "warning", "timeout": 4},
                )
            ]
