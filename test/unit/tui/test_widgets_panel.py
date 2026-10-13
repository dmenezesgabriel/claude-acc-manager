"""TUI widgets — the AccountsPanel list and the interactive widgets.

Panel composition, selection behavior, and widget-level rendering exercised
through a pilot-driven app.
"""

from support.fake_usage_api import FakeUsageApi
from support.rich_asserts import visual_plain as _visual_plain
from support.rich_asserts import visual_span_styles as _visual_span_styles
from support.tui_app import settle_workers, wired_app
from support.tui_views import DARK, LIGHT, NOW
from support.tui_views import account_view as _view
from support.tui_views import usage_snapshot as _snapshot
from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.screen import Screen
from textual.visual import Visual
from textual.widget import Widget
from textual.widgets import ListView, Static

from claude_acc_manager.tui.theme import CAM_DARK, CAM_LIGHT, MUTED_LIGHT
from claude_acc_manager.tui.visuals import AccountCardVisual
from claude_acc_manager.tui.widgets import (
    AccountCard,
    AccountItem,
    AccountsPanel,
    MenuItem,
)
from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot, UsageWindow


class TestAccountsPanel:
    """The dashboard's monitor — Pilot-mounted inside a real CamApp."""

    async def test_loading_until_the_first_snapshot_lands(self, tmp_path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            panel = app.screen.query_one(AccountsPanel)
            app.snapshot = None
            text = panel.render()
            assert text.plain == "loading…"
            assert str(text.style) == DARK.muted

    async def test_the_active_card_then_the_minis(self, tmp_path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path, active_name="work")
        # minis render only at ≥100 cols — the narrow class collapses them
        async with app.run_test(size=(120, 24)) as pilot:
            await settle_workers(pilot)
            render = app.screen.query_one(AccountsPanel).render()
            assert isinstance(render, Visual)
            lines = _visual_plain(render, 120).splitlines()
            assert "● active" in lines[0]
            # the expanded card rows sit between the two account headers
            assert any(line.strip().startswith("5h") for line in lines)
            assert any("personal" in line and "·" not in line for line in lines)
            # a blank line separates the card from the minis, none between
            personal_at = next(i for i, r in enumerate(lines) if "personal" in r)
            assert lines[personal_at - 1] == ""

    async def test_no_accounts_reads_empty(self, tmp_path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path, names=())
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            panel = app.screen.query_one(AccountsPanel)
            text = panel.render()
            assert text.plain.startswith("No managed accounts yet")
            assert "cam add" in text.plain
            assert str(text.style) == DARK.muted

    async def test_minis_off_with_no_active_login_says_so(self, tmp_path) -> None:
        # the auto preview mounts the panel with minis off; nothing active
        # must not silently render a blank block
        app, _api, _store, _clock = wired_app(tmp_path)

        class _PanelScreen(Screen[None]):
            def compose(self) -> ComposeResult:
                yield AccountsPanel(show_minis=False)

        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app.push_screen(_PanelScreen())
            await pilot.pause()
            panel = app.screen.query_one(AccountsPanel)
            text = panel.render()
            assert text.plain == "no active managed login"
            assert str(text.style) == DARK.muted

    async def test_minis_off_with_an_active_login_shows_the_card(self, tmp_path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path, active_name="work")

        class _PanelScreen(Screen[None]):
            def compose(self) -> ComposeResult:
                yield AccountsPanel(show_minis=False)

        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app.push_screen(_PanelScreen())
            await pilot.pause()
            text = _visual_plain(app.screen.query_one(AccountsPanel).render(), 400)
            assert "work" in text
            assert "personal" not in text

    async def test_the_panel_hides_emails_until_p_shows_them(self, tmp_path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path, active_name="work")
        async with app.run_test(size=(120, 24)) as pilot:
            await settle_workers(pilot)
            panel = app.screen.query_one(AccountsPanel)
            assert "example.com" not in _visual_plain(panel.render(), 400)
            await pilot.press("p")
            await pilot.pause()
            text = _visual_plain(panel.render(), 400)
            assert "work@example.com" in text
            assert "personal@example.com" in text

    async def test_a_theme_flip_repaints_the_panel(self, tmp_path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path, active_name="work")
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            panel = app.screen.query_one(AccountsPanel)
            render = panel.render()
            assert isinstance(render, Visual)
            assert MUTED_LIGHT not in _visual_span_styles(render, 400)
            await pilot.press("ctrl+t")
            render = panel.render()
            assert isinstance(render, Visual)
            assert MUTED_LIGHT in _visual_span_styles(render, 400)

    async def test_the_panel_forwards_the_app_threshold(self, tmp_path) -> None:
        # the seeded account reads 95% — the 90% trigger line must cross it
        hi = UsageSnapshot(
            five_hour=UsageWindow(pct=95.0, resets_at=None),
            seven_day=None,
            scoped=(),
        )
        app, _api, _store, _clock = wired_app(
            tmp_path, active_name="work", usage_api=FakeUsageApi(snapshot=hi)
        )
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            render = app.screen.query_one(AccountsPanel).render()
            assert isinstance(render, Visual)
            assert "┃" in _visual_plain(render, 400)

    async def test_the_panel_repaints_on_snapshot_and_theme(self, tmp_path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path, active_name="work")
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            panel = app.screen.query_one(AccountsPanel)
            repaints: list[dict[str, object]] = []
            panel.refresh = lambda **kw: repaints.append(kw)
            app.snapshot = None
            app.theme = "cam-light"
            await pilot.pause()
            # the watcher's signature call is layout=True; a theme flip also
            # triggers Textual's own layout=False repaints — those don't count
            watcher_repaints = [kw for kw in repaints if kw == {"layout": True}]
            assert len(watcher_repaints) == 2

    async def test_the_panel_repaints_on_a_privacy_flip(self, tmp_path) -> None:
        # the panel reads app.redact_emails at render time; only the watcher
        # makes the on-screen copy follow a live p toggle
        app, _api, _store, _clock = wired_app(tmp_path, active_name="work")
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            panel = app.screen.query_one(AccountsPanel)
            repaints: list[dict[str, object]] = []
            panel.refresh = lambda **kw: repaints.append(kw)
            await pilot.press("p")
            await pilot.pause()
            assert {"layout": True} in repaints

    async def test_unmounted_render_uses_the_fallback_width(self, tmp_path) -> None:
        # before first layout a widget's size is 0 — the fallback keeps the
        # card at its 30-cell bar width instead of collapsing to the floor
        app, _api, _store, _clock = wired_app(tmp_path, active_name="work")
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            render = AccountsPanel().render()
            assert isinstance(render, Visual)
            text = _visual_plain(render, 400)
            line = next(line for line in text.splitlines() if "5h" in line)
            glyphs = sum(line.count(g) for g in "━─╸┃")
            assert glyphs == 30

    def test_the_panel_forwards_its_id(self) -> None:
        assert AccountsPanel(id="accounts-panel").id == "accounts-panel"

    def test_unmounted_panels_are_not_narrow(self) -> None:
        # no screen → no breakpoint class — an unmounted render keeps minis
        assert AccountsPanel()._narrow() is False

    def test_blocks_forward_the_palette_to_the_card(self) -> None:
        # unmounted: width falls back to _UNMOUNTED_WIDTH — a dropped palette
        # kwarg would render in the dark theme instead of the given one
        view = _view("work", is_active=True, last_good=_snapshot())
        blocks = AccountsPanel()._blocks((view,), NOW, 90.0, LIGHT, False)
        assert isinstance(blocks[0], AccountCardVisual)
        assert LIGHT.sev_ok in _visual_span_styles(blocks[0], 400)

    def test_blocks_forward_the_palette_to_the_minis(self) -> None:
        view = _view("work", is_active=False, last_good=_snapshot())
        blocks = AccountsPanel()._blocks((view,), NOW, 90.0, LIGHT, False)
        assert LIGHT.muted in _visual_span_styles(blocks[0], 400)


class _WidgetApp(App[None]):
    """Bare host — mounts fixtures without CamApp's poll machinery."""

    def __init__(self, *widgets: Widget, theme: str = "cam-dark") -> None:
        super().__init__()
        self._widgets = widgets
        self.register_theme(CAM_DARK)
        self.register_theme(CAM_LIGHT)
        self.theme = theme

    def compose(self) -> ComposeResult:
        yield from self._widgets

    # AccountCard reads this off the app — hidden is the safe stub default.
    redact_emails: reactive[bool] = reactive(True)

    def now_s(self) -> float:
        """The injected-clock seam the widgets read from the app."""
        return NOW


class TestAccountWidgets:
    async def test_an_account_item_renders_its_card(self) -> None:
        view = _view("work", is_active=True, last_good=None)
        app = _WidgetApp(ListView(AccountItem(view)))
        async with app.run_test() as pilot:
            await pilot.pause()
            item = app.screen.query_one(AccountItem)
            assert item.account_name.value == "work"
            render = app.screen.query_one(AccountCard).render()
            assert isinstance(render, AccountCardVisual)
            text = _visual_plain(render, 400)
            assert "work" in text
            assert "usage unavailable" in text

    async def test_the_card_passes_its_threshold_to_the_bar(self) -> None:
        snap = UsageSnapshot(
            five_hour=UsageWindow(pct=95.0, resets_at=None),
            seven_day=None,
            scoped=(),
        )
        app = _WidgetApp(AccountCard(_view("work", last_good=snap), threshold=90.0))
        async with app.run_test() as pilot:
            await pilot.pause()
            render = app.screen.query_one(AccountCard).render()
            assert isinstance(render, Visual)
            assert "┃" in _visual_plain(render, 400)

    async def test_an_unmounted_card_falls_back_to_full_width(self) -> None:
        # a falsy width must take the fallback branch, not a truthiness chain
        app = _WidgetApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            card = AccountCard(_view("work", last_good=_snapshot()))
            render = card.render()
            assert isinstance(render, Visual)
            line = next(line for line in _visual_plain(render, 400).splitlines() if "5h" in line)
            assert sum(line.count(g) for g in "━─╸┃") == 30

    async def test_the_card_render_uses_the_theme_palette(self) -> None:
        app = _WidgetApp(theme="cam-light")
        async with app.run_test() as pilot:
            await pilot.pause()
            card = AccountCard(_view("work", last_good=_snapshot()))
            render = card.render()
            assert isinstance(render, Visual)
            assert LIGHT.sev_ok in _visual_span_styles(render, 400)

    async def test_the_card_hides_the_email_by_default(self) -> None:
        app = _WidgetApp(ListView(AccountItem(_view("work", last_good=_snapshot()))))
        async with app.run_test() as pilot:
            await pilot.pause()
            render = app.screen.query_one(AccountCard).render()
            assert isinstance(render, Visual)
            assert "work@example.com" not in _visual_plain(render, 400)

    async def test_a_privacy_flip_repaints_the_card(self) -> None:
        app = _WidgetApp(ListView(AccountItem(_view("work", last_good=None))))
        async with app.run_test() as pilot:
            await pilot.pause()
            card = app.screen.query_one(AccountCard)
            repaints: list[dict[str, object]] = []
            card.refresh = lambda **kw: repaints.append(kw)
            app.redact_emails = False
            assert {"layout": True} in repaints

    async def test_set_account_repoints_and_repaints_the_card(self) -> None:
        app = _WidgetApp(ListView(AccountItem(_view("work", last_good=None))))
        async with app.run_test() as pilot:
            await pilot.pause()
            item = app.screen.query_one(AccountItem)
            card = app.screen.query_one(AccountCard)
            repaints: list[dict[str, object]] = []
            card.refresh = lambda **kw: repaints.append(kw)
            item.set_account(_view("personal", last_good=None))
            assert item.account_name.value == "personal"
            assert repaints == [{"layout": True}]
            render = card.render()
            assert isinstance(render, Visual)
            assert "personal" in _visual_plain(render, 400)

    async def test_a_menu_item_carries_its_action(self) -> None:
        app = _WidgetApp(
            ListView(
                MenuItem("Switch [b]account[/b]", "switch"),
                MenuItem("Muted row", "none", muted=True),
            )
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            items = list(app.screen.query(MenuItem))
            assert items[0].action_id == "switch"
            label = items[0].query_one(Static)
            assert "menu-item-muted" not in label.classes
            # markup stays literal — labels are data, not formatting
            assert label.render().plain == "Switch [b]account[/b]"
            assert items[1].action_id == "none"
            assert "menu-item-muted" in items[1].query_one(Static).classes
