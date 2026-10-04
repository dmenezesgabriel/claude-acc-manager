"""The F1 help panel — grouped bindings plus per-screen HELP markdown.

``HelpPanel`` is textual's built-in: F1 toggles it (the app defines the
``toggle_help_panel`` action), and the panel renders the focused widget's
nearest ancestor ``HELP`` markdown next to the screen's key table.
"""

from pathlib import Path

from support.tui_app import settle_workers, wired_app
from textual.widgets import HelpPanel, Markdown

from claude_acc_manager.tui.account_list import SwitchScreen, WatchScreen
from claude_acc_manager.tui.app import CamApp
from claude_acc_manager.tui.autoview import AutoScreen
from claude_acc_manager.tui.dashboard import DashboardScreen
from claude_acc_manager.tui.modals import ConfirmModal

_BOUNDED_SCREENS = (DashboardScreen, SwitchScreen, WatchScreen, AutoScreen, ConfirmModal)


def _help_markdown(app: CamApp) -> str:
    """The markdown the help panel renders for the focused widget."""
    return app.screen.query(HelpPanel).first().query_one(Markdown).source


class TestHelpPanelToggle:
    async def test_f1_opens_the_help_panel(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            assert not app.screen.query(HelpPanel)
            await pilot.press("f1")
            await pilot.pause()
            assert app.screen.query(HelpPanel)

    async def test_f1_again_dismisses_it(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await pilot.press("f1")
            await pilot.pause()
            await pilot.press("f1")
            await pilot.pause()
            assert not app.screen.query(HelpPanel)


class TestContextualHelp:
    async def test_the_dashboard_focus_shows_menu_help(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await pilot.press("f1")
            await pilot.pause()
            # the focused #menu's ancestor chain resolves DashboardScreen.HELP
            assert "menu" in _help_markdown(app).lower()

    async def test_the_watch_screen_helps_with_selection(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app.push_screen(WatchScreen())
            await pilot.pause()
            await pilot.press("f1")
            await pilot.pause()
            assert "watch" in _help_markdown(app).lower()

    async def test_the_switch_screen_helps_with_switching(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app.push_screen(SwitchScreen())
            await pilot.pause()
            await pilot.press("f1")
            await pilot.pause()
            assert "switch" in _help_markdown(app).lower()


class TestBindingMetadata:
    """The metadata the panel renders — groups, tooltips, key display."""

    def test_the_app_names_its_binding_group(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        assert CamApp.BINDING_GROUP_TITLE
        assert app.BINDING_GROUP_TITLE == CamApp.BINDING_GROUP_TITLE

    def test_every_screen_names_its_binding_group(self) -> None:
        for screen in _BOUNDED_SCREENS:
            assert screen.BINDING_GROUP_TITLE, screen.__name__

    def test_every_binding_carries_a_tooltip(self) -> None:
        for screen in (CamApp, *_BOUNDED_SCREENS):
            for binding in screen.BINDINGS:
                assert binding.tooltip, f"{screen.__name__}: {binding.key}"

    def test_multikey_bindings_declare_a_display_name(self) -> None:
        # "escape,q,s" would render raw; key_display names what shows instead
        for screen in _BOUNDED_SCREENS:
            for binding in screen.BINDINGS:
                if "," in binding.key:
                    assert binding.key_display, f"{screen.__name__}: {binding.key}"
