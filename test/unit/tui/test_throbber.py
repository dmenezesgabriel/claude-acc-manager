"""The busy throbber — a gradient sweep shown while an action runs.

``ThrobberVisual`` renders one ``━``-per-cell strip whose colors ride a
muted→accent→muted gradient; the window slides with wall time. The
``Throbber`` widget stays hidden until ``app.busy`` adds ``-busy``.
"""

from pathlib import Path

from support.tui_app import settle_workers, wired_app
from textual.color import Color, Gradient
from textual.containers import Horizontal
from textual.css.styles import RulesMap
from textual.strip import Strip
from textual.style import Style
from textual.visual import RenderOptions

from claude_acc_manager.tui.dashboard import DashboardScreen
from claude_acc_manager.tui.theme import Palette
from claude_acc_manager.tui.throbber import LoadingBar, Throbber, ThrobberVisual
from claude_acc_manager.tui.widgets import AccountsPanel

_OPTIONS = RenderOptions(get_style=lambda _style: Style(), rules=RulesMap())

# black→white→black: symmetric so the sweep midpoint is unambiguous.
_BW = Gradient.from_colors(Color.parse("#000000"), Color.parse("#ffffff"), Color.parse("#000000"))


def _strip_at(width: int, t: float) -> Strip:
    """Render one strip of a deterministic (frozen-time) sweep."""
    visual = ThrobberVisual(_BW, get_time=lambda: t)
    return visual.render_strips(width, 1, Style(), _OPTIONS)[0]


class TestThrobberVisual:
    def test_renders_one_full_width_strip(self) -> None:
        strip = _strip_at(10, 0.0)
        assert strip.cell_length == 10
        assert strip.text == "━" * 10
        assert len(list(strip)) == 10  # one segment per cell — no gaps

    def test_cells_carry_the_widget_background(self) -> None:
        visual = ThrobberVisual(_BW, get_time=lambda: 0.0)
        strip = visual.render_strips(8, 1, Style.parse("on #112233"), _OPTIONS)[0]
        for seg in strip:
            assert seg.style.bgcolor is not None
            assert seg.style.bgcolor.get_truecolor() == (0x11, 0x22, 0x33)

    def test_edges_are_dark_and_the_middle_is_bright(self) -> None:
        strip = _strip_at(8, 0.0)
        colors = [seg.style.color for seg in strip]
        dark = colors[0]
        bright = colors[4]
        assert dark is not None and dark.get_truecolor().red < 0x40
        assert bright is not None and bright.get_truecolor().red > 0xC0

    def test_the_sweep_moves_with_time(self) -> None:
        # half a second later the gradient window has slid half a width
        assert _strip_at(8, 0.0) != _strip_at(8, 0.5)
        assert _strip_at(8, 0.0) == _strip_at(8, 1.0)  # and wraps each second

    def test_every_time_still_fills_the_width(self) -> None:
        # the window stays width-long at any offset — even wrapped ones
        for t in (0.5, 1.5, 2.0):
            assert len(list(_strip_at(8, t))) == 8

    def test_fills_the_container_width_and_stays_one_row(self) -> None:
        visual = ThrobberVisual(_BW, get_time=lambda: 0.0)
        assert visual.get_optimal_width(RulesMap(), 40) == 40
        assert visual.get_height(RulesMap(), 40) == 1

    def test_segment_runs_are_cached_per_width(self) -> None:
        visual = ThrobberVisual(_BW, get_time=lambda: 0.0)
        style = Style()
        assert visual.make_segments(style, 8) is visual.make_segments(style, 8)
        assert visual.make_segments(style, 8) is not visual.make_segments(style, 16)

    def test_the_run_is_two_cycles_long(self) -> None:
        visual = ThrobberVisual(_BW, get_time=lambda: 0.0)
        assert len(visual.make_segments(Style(), 8)) == 16


class TestThrobberWiring:
    async def test_hidden_until_busy_then_shown(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            assert isinstance(app.screen, DashboardScreen)
            throbber = app.screen.query_one("#throbber", Throbber)
            assert not throbber.has_class("-busy")
            app.busy = True
            await pilot.pause()
            assert throbber.has_class("-busy")
            app.busy = False
            await pilot.pause()
            assert not throbber.has_class("-busy")

    async def test_the_title_rows_host_the_throbber(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            row = app.screen.query_one("#menu-title-row", Horizontal)
            row.query_one(Throbber)
            await pilot.press("w")
            await pilot.pause()
            row = app.screen.query_one("#list-title-row", Horizontal)
            row.query_one(Throbber)

    async def test_render_sweeps_muted_accent_muted(self, tmp_path: Path) -> None:
        # palette-muted ends, palette-accent midpoint — the gradient's
        # public ramp is [muted … accent … muted]
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            palette = Palette.from_theme(app.current_theme)
            visual = app.screen.query_one("#throbber", Throbber).render()
            colors = visual.gradient.colors
            muted = Color.parse(palette.muted).rgb
            accent = Color.parse(palette.accent).rgb
            assert colors[0].rgb == muted
            assert colors[-1].rgb == muted
            # the ramp interpolates in Lab space — the midpoint lands on the
            # accent stop only to within a couple of channel points
            mid = colors[len(colors) // 2].rgb
            assert abs(mid[0] - accent[0]) <= 4
            assert muted != accent

    async def test_auto_refresh_is_a_fifteenth_of_a_second(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            throbber = app.screen.query_one("#throbber", Throbber)
            assert throbber.auto_refresh == 1 / 15

    async def test_mounted_on_watch_and_auto_screens(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await pilot.press("w")
            await pilot.pause()
            app.screen.query_one("#throbber", Throbber)
            await pilot.press("escape")
            await pilot.press("g")
            await settle_workers(pilot)
            app.screen.query_one("#throbber", Throbber)


class TestLoadingBar:
    """The branded ``.loading`` cover — the sweep with no busy gate."""

    def test_get_loading_widget_returns_the_branded_sweep(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        assert isinstance(app.get_loading_widget(), LoadingBar)

    async def test_a_loading_state_covers_with_the_sweep(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            panel = app.screen.query_one(AccountsPanel)
            panel.loading = True
            await pilot.pause()
            cover = panel._cover_widget
            assert isinstance(cover, LoadingBar)
            assert cover.has_class("-textual-loading-indicator")
            # Independent of app.busy — the header Throbber's -busy gate
            # and its visibility:hidden CSS must not reach the cover.
            app.busy = True
            await pilot.pause()
            assert not cover.has_class("-busy")
            assert cover.styles.visibility == "visible"
            assert cover.auto_refresh == 1 / 15
            assert isinstance(cover.render(), ThrobberVisual)
