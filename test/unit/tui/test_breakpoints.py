"""Narrow-terminal breakpoints (slice T9).

``HORIZONTAL_BREAKPOINTS`` lands ``-narrow``/``-wide`` on the screen;
``AccountsPanel`` reads the class and drops the mini rows so the active
card keeps full width around 60 columns.
"""

from __future__ import annotations

from pathlib import Path

from support.rich_asserts import visual_plain
from support.tui_app import settle_workers, wired_app

from claude_acc_manager.tui.widgets import AccountsPanel


class TestBreakpointClasses:
    async def test_narrow_class_lands_at_60_columns(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test(size=(60, 24)) as pilot:
            await settle_workers(pilot)
            assert app.screen.has_class("-narrow")
            assert not app.screen.has_class("-wide")

    async def test_wide_class_lands_at_120_columns(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test(size=(120, 24)) as pilot:
            await settle_workers(pilot)
            assert app.screen.has_class("-wide")
            assert not app.screen.has_class("-narrow")

    async def test_resizing_flips_the_class(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path)
        async with app.run_test(size=(120, 24)) as pilot:
            await settle_workers(pilot)
            await pilot.resize_terminal(60, 24)
            await pilot.pause()
            assert app.screen.has_class("-narrow")
            await pilot.resize_terminal(120, 24)
            await pilot.pause()
            assert app.screen.has_class("-wide")


class TestNarrowLayout:
    async def test_minis_render_when_wide(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path, active_name="personal")
        async with app.run_test(size=(120, 24)) as pilot:
            await settle_workers(pilot)
            panel = app.screen.query_one(AccountsPanel)
            assert "work" in visual_plain(panel.render(), 120)

    async def test_minis_collapse_when_narrow(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path, active_name="personal")
        async with app.run_test(size=(60, 24)) as pilot:
            await settle_workers(pilot)
            panel = app.screen.query_one(AccountsPanel)
            rendered = visual_plain(panel.render(), 60)
            assert "personal" in rendered
            assert "work" not in rendered

    async def test_a_resize_to_narrow_collapses_minis_live(self, tmp_path: Path) -> None:
        app, *_ = wired_app(tmp_path, active_name="personal")
        async with app.run_test(size=(120, 24)) as pilot:
            await settle_workers(pilot)
            panel = app.screen.query_one(AccountsPanel)
            assert "work" in visual_plain(panel.render(), 120)
            await pilot.resize_terminal(60, 24)
            await pilot.pause()
            assert "work" not in visual_plain(panel.render(), 60)
