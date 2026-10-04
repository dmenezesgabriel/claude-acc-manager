"""The generated settings modal (slice T6 read path).

One editor row per ``SETTING_SPECS`` key — ``Input``+``Number`` for float
kinds, ``Select`` for choice — seeded with the effective values from
``list_settings``. The write path lands in T7.
"""

from __future__ import annotations

from pathlib import Path

from support.in_memory_settings import InMemorySettings
from support.tui_app import settle_workers, wired_app
from textual.widgets import Input, Select, Static

from claude_acc_manager.settings.domain.settings_spec import SETTING_SPECS, setting_spec
from claude_acc_manager.tui.dashboard import DashboardScreen
from claude_acc_manager.tui.settings_screen import SettingsScreen
from claude_acc_manager.tui.widgets import MenuItem


class TestEntryPoints:
    async def test_the_menu_has_a_settings_row(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            labels = [str(item.query_one(Static).content) for item in app.screen.query(MenuItem)]
            assert "c  Settings…" in labels

    async def test_the_settings_row_opens_the_modal(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await pilot.press("c")
            await pilot.pause()
            assert isinstance(app.screen, SettingsScreen)

    async def test_escape_dismisses_back_to_the_dashboard(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app.push_screen(SettingsScreen())
            await pilot.pause()
            assert isinstance(app.screen, SettingsScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, DashboardScreen)

    async def test_the_modal_carries_a_screen_title(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            app.push_screen(SettingsScreen())
            await pilot.pause()
            assert app.screen.title == "settings"


class TestGeneratedRows:
    async def test_one_editor_per_spec_key(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            app.push_screen(SettingsScreen())
            await pilot.pause()
            float_count = sum(1 for spec in SETTING_SPECS.values() if spec.kind == "float")
            choice_count = sum(1 for spec in SETTING_SPECS.values() if spec.kind == "choice")
            assert len(app.screen.query(Input)) == float_count
            assert len(app.screen.query(Select)) == choice_count

    async def test_a_float_key_seeds_a_number_input(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            app.push_screen(SettingsScreen())
            await pilot.pause()
            threshold = app.screen.query_one("#setting-threshold", Input)
            assert threshold.value == "90"
            assert threshold.type == "number"

    async def test_the_choice_key_seeds_a_select(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            app.push_screen(SettingsScreen())
            await pilot.pause()
            strategy = app.screen.query_one("#setting-strategy", Select)
            assert strategy.value == "best"
            option_values = [option[1] for option in strategy._options]
            assert option_values == list(setting_spec("autoswitch.strategy").choices)

    async def test_a_hand_set_value_seeds_the_editor(self, tmp_path: Path) -> None:
        settings = InMemorySettings(tmp_path)
        settings.set_value(setting_spec("autoswitch.threshold"), 80.0)
        app, *_ = wired_app(tmp_path, settings=settings)
        async with app.run_test() as pilot:
            app.push_screen(SettingsScreen())
            await pilot.pause()
            threshold = app.screen.query_one("#setting-threshold", Input)
            assert threshold.value == "80"

    async def test_the_number_validator_carries_the_spec_bounds(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            app.push_screen(SettingsScreen())
            await pilot.pause()
            spec = setting_spec("autoswitch.threshold")
            threshold = app.screen.query_one("#setting-threshold", Input)
            bounds = [(v.minimum, v.maximum) for v in threshold.validators]
            assert bounds == [(spec.lo, spec.hi)]

    async def test_every_spec_key_labels_a_row(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            app.push_screen(SettingsScreen())
            await pilot.pause()
            rendered = "\n".join(
                str(static.render()) for static in app.screen.query(".setting-name")
            )
            for dotted in SETTING_SPECS:
                assert dotted in rendered

    async def test_the_modal_shell_carries_its_ids(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            app.push_screen(SettingsScreen())
            await pilot.pause()
            assert app.screen.query_one("#settings")
            title = app.screen.query_one("#settings-title", Static)
            assert str(title.render()) == "settings"

    async def test_each_row_is_a_setting_container(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            app.push_screen(SettingsScreen())
            await pilot.pause()
            assert len(app.screen.query(".setting")) == len(SETTING_SPECS)

    async def test_each_row_shows_the_spec_help(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            app.push_screen(SettingsScreen())
            await pilot.pause()
            rendered = "\n".join(
                str(static.render()) for static in app.screen.query(".setting-help")
            )
            for spec in SETTING_SPECS.values():
                assert spec.help in rendered

    async def test_the_choice_editor_cannot_be_blank(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test() as pilot:
            app.push_screen(SettingsScreen())
            await pilot.pause()
            strategy = app.screen.query_one("#setting-strategy", Select)
            assert strategy._allow_blank is False

    async def test_a_hand_set_choice_seeds_the_select(self, tmp_path: Path) -> None:
        settings = InMemorySettings(tmp_path)
        settings.set_value(setting_spec("autoswitch.strategy"), "next-available")
        app, *_ = wired_app(tmp_path, settings=settings)
        async with app.run_test() as pilot:
            app.push_screen(SettingsScreen())
            await pilot.pause()
            strategy = app.screen.query_one("#setting-strategy", Select)
            assert strategy.value == "next-available"
