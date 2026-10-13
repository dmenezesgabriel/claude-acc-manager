"""``Visual``/``Strip`` renderers — bars, minis, cards, and stacked joins.

Each card visual composes a header line with one ``UsageBarVisual`` per
usage window; stacked visuals leave a blank strip only around multi-line
blocks — the exact semantics the old ``_join_blocks`` text join had.
"""

from rich.text import Text
from support.rich_asserts import (
    VISUAL_OPTIONS,
    strip_style_at,
    visual_plain,
    visual_strips,
    visual_style_at,
)
from support.tui_app import settle_workers, wired_app
from support.tui_views import DARK, LIGHT, NOW
from support.tui_views import account_view as _view
from support.tui_views import usage_snapshot as _snapshot
from textual.css.styles import RulesMap
from textual.style import Style
from textual.visual import Visual

from claude_acc_manager.tui.visuals import (
    AccountCardVisual,
    MiniAccountVisual,
    StackedVisual,
    UsageBarVisual,
    _ContentVisual,
)
from claude_acc_manager.tui.widgets import AccountCard, AccountsPanel
from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot, UsageWindow


class TestUsageBarVisual:
    def test_renders_one_indented_bar_row(self) -> None:
        strips = visual_strips(UsageBarVisual("5h", 47.0, "resets 2h 13m", 10, palette=DARK), 60)
        assert len(strips) == 1
        assert strips[0].text.startswith("    5h ")
        assert "━" in strips[0].text
        assert "resets 2h 13m" in strips[0].text

    def test_bar_width_follows_the_cells_argument(self) -> None:
        narrow = visual_plain(UsageBarVisual("5h", 47.0, None, 10, palette=DARK))
        wide = visual_plain(UsageBarVisual("5h", 47.0, None, 20, palette=DARK))
        assert sum(narrow.count(g) for g in "━─╸┃") == 10
        assert sum(wide.count(g) for g in "━─╸┃") == 20

    def test_palette_reaches_the_cells(self) -> None:
        visual = UsageBarVisual("5h", 20.0, None, 10, palette=LIGHT)
        strips = visual_strips(visual, 60)
        assert strip_style_at(strips[0], 4) == LIGHT.muted
        assert strip_style_at(strips[0], 7) == LIGHT.sev_ok

    def test_the_indent_is_unstyled(self) -> None:
        strips = visual_strips(UsageBarVisual("5h", 47.0, None, 10, palette=DARK), 60)
        assert strip_style_at(strips[0], 0) == "none"


class TestMiniAccountVisual:
    def test_renders_a_single_line(self) -> None:
        visual = MiniAccountVisual(
            _view("work", last_good=_snapshot()), NOW, palette=DARK, redact=False
        )
        strips = visual_strips(visual, 100)
        assert len(strips) == 1
        assert "work (work@example.com)" in strips[0].text
        assert "47% · 7d" in strips[0].text

    def test_a_mini_is_never_multiline(self) -> None:
        assert MiniAccountVisual(_view("work"), NOW, palette=DARK, redact=False).multiline is False

    def test_redaction_drops_the_email_span(self) -> None:
        visual = MiniAccountVisual(
            _view("work", last_good=_snapshot()), NOW, palette=DARK, redact=True
        )
        strips = visual_strips(visual, 100)
        assert strips[0].text.startswith("work   ")
        assert "work@example.com" not in strips[0].text

    def test_dimensions_track_the_content(self) -> None:
        visual = MiniAccountVisual(
            _view("work", last_good=_snapshot()), NOW, palette=DARK, redact=False
        )
        rules = RulesMap()
        assert visual.get_height(rules, 100) == 1
        assert visual.get_optimal_width(rules, 100) == len(visual_plain(visual, 100))
        assert visual.get_minimal_width(rules) >= 4  # longest word ≥ "work"


class TestAccountCardVisual:
    def test_the_card_is_a_visual(self) -> None:
        visual = AccountCardVisual(
            _view("work", is_active=True, last_good=_snapshot()),
            80,
            threshold=90.0,
            now=NOW,
            palette=DARK,
            redact=False,
        )
        assert isinstance(visual, Visual)
        assert visual.multiline is True
        # a card's own lines join directly — the flag is for panel siblings
        assert visual._pad_multiline is False

    def test_header_then_bar_rows(self) -> None:
        visual = AccountCardVisual(
            _view("work", is_active=True, last_good=_snapshot()),
            80,
            threshold=90.0,
            now=NOW,
            palette=DARK,
            redact=False,
        )
        lines = visual_plain(visual).splitlines()
        assert lines[0] == "work (work@example.com)   ● active"
        assert lines[1].strip().startswith("5h")
        assert lines[2].strip().startswith("7d")
        assert len(lines) == 3

    def test_redaction_drops_the_email_from_the_header(self) -> None:
        visual = AccountCardVisual(
            _view("work", is_active=True, last_good=_snapshot()),
            80,
            threshold=90.0,
            now=NOW,
            palette=DARK,
            redact=True,
        )
        lines = visual_plain(visual).splitlines()
        assert lines[0] == "work   ● active"
        assert len(lines) == 3

    def test_height_matches_the_strip_count(self) -> None:
        visual = AccountCardVisual(
            _view("work", is_active=True, last_good=_snapshot()),
            80,
            now=NOW,
            palette=DARK,
            redact=False,
        )
        assert visual.get_height(RulesMap(), 80) == 3

    def test_the_threshold_tick_reaches_the_rows(self) -> None:
        snap = UsageSnapshot(
            five_hour=UsageWindow(pct=95.0, resets_at=None), seven_day=None, scoped=()
        )
        visual = AccountCardVisual(
            _view("work", is_active=True, last_good=snap),
            80,
            threshold=90.0,
            now=NOW,
            palette=DARK,
            redact=False,
        )
        assert "┃" in visual_plain(visual)

    def test_quarantined_shows_the_warning(self) -> None:
        visual = AccountCardVisual(
            _view("work", is_quarantined=True, last_good=None, last_error="x"),
            80,
            now=NOW,
            palette=DARK,
            redact=False,
        )
        lines = visual_plain(visual).splitlines()
        assert lines[1] == "    ⚠ quarantined — dead refresh-token lineage"
        plain = visual_plain(visual)
        assert DARK.sev_warn in visual_style_at(visual, plain.index("⚠"))

    def test_no_usage_reads_unavailable(self) -> None:
        visual = AccountCardVisual(
            _view("work", last_good=None, last_error="http-429"),
            80,
            now=NOW,
            palette=DARK,
            redact=False,
        )
        lines = visual_plain(visual).splitlines()
        assert lines[1] == "    usage unavailable · http-429"


class TestStackedJoins:
    """The panel's block join: minis pack tight, cards get a blank line."""

    def _minis_and_card(self) -> list[Visual]:
        card = AccountCardVisual(
            _view("work", is_active=True, last_good=_snapshot()),
            80,
            now=NOW,
            palette=DARK,
            redact=False,
        )
        mini1 = MiniAccountVisual(
            _view("personal", last_good=_snapshot()), NOW, palette=DARK, redact=False
        )
        mini2 = MiniAccountVisual(
            _view("other", last_good=_snapshot()), NOW, palette=DARK, redact=False
        )
        return [card, mini1, mini2]

    def test_a_card_is_separated_from_minis_by_a_blank_line(self) -> None:
        blocks = self._minis_and_card()
        plain = visual_plain(StackedVisual(blocks), 100)
        lines = plain.splitlines()
        personal_at = next(i for i, r in enumerate(lines) if "personal" in r)
        assert lines[personal_at - 1] == ""
        # minis stay packed: no blank between them
        other_at = next(i for i, r in enumerate(lines) if "other" in r)
        assert lines[other_at - 1].strip() != ""

    def test_strip_count_includes_the_gap(self) -> None:
        blocks = self._minis_and_card()
        stack = StackedVisual(blocks)
        # card renders 3 lines + 1 gap + 2 minis
        assert len(visual_strips(stack, 100)) == 6
        assert stack.get_height(RulesMap(), 100) == 6

    def test_height_cut_truncates_from_the_bottom(self) -> None:
        blocks = self._minis_and_card()
        stack = StackedVisual(blocks)
        strips = stack.render_strips(100, 2, Style(), VISUAL_OPTIONS)
        assert len(strips) == 2

    def test_the_blank_gap_is_width_wide(self) -> None:
        blocks = self._minis_and_card()
        stack = StackedVisual(blocks)
        gap = visual_strips(stack, 100)[3]
        assert gap.text == " " * 100

    def test_the_separator_inherits_the_base_style(self) -> None:
        blocks = [_ContentVisual(Text("a\nb")), _ContentVisual(Text("c"))]
        style = Style.parse("on #112233")
        strips = StackedVisual(blocks).render_strips(40, None, style, VISUAL_OPTIONS)
        assert "#112233" in strip_style_at(strips[2], 0)

    def test_minis_only_pack_with_no_gap(self) -> None:
        minis = [
            MiniAccountVisual(
                _view("personal", last_good=_snapshot()), NOW, palette=DARK, redact=False
            ),
            MiniAccountVisual(
                _view("other", last_good=_snapshot()), NOW, palette=DARK, redact=False
            ),
        ]
        stack = StackedVisual(minis)
        assert len(visual_strips(stack, 100)) == 2
        assert stack.get_height(RulesMap(), 100) == 2

    def test_multiline_blocks_get_air_but_single_line_ones_join_tight(self) -> None:
        # the pre-Visual text join: "card\nrow" + minis → "card\nrow\n\nmini1\nmini2"
        blocks = [
            _ContentVisual(Text("card\nrow")),
            _ContentVisual(Text("mini1")),
            _ContentVisual(Text("mini2")),
        ]
        assert visual_plain(StackedVisual(blocks), 40) == "card\nrow\n\nmini1\nmini2"

    def test_single_line_blocks_join_with_no_blank(self) -> None:
        blocks = [_ContentVisual(Text("a")), _ContentVisual(Text("b"))]
        assert visual_plain(StackedVisual(blocks), 40) == "a\nb"

    def test_a_multiline_second_block_also_gets_air(self) -> None:
        # the pad rule looks at *either* side of the boundary
        blocks = [_ContentVisual(Text("mini")), _ContentVisual(Text("card\nrow"))]
        assert visual_plain(StackedVisual(blocks), 40) == "mini\n\ncard\nrow"

    def test_optimal_width_is_the_widest_part(self) -> None:
        stack = StackedVisual([_ContentVisual(Text("ab")), _ContentVisual(Text("abcdef"))])
        rules = RulesMap()
        assert stack.get_optimal_width(rules, 100) == 6
        assert stack.get_minimal_width(rules) == 6
        assert stack.multiline is True

    def test_an_empty_stack_measures_zero(self) -> None:
        stack = StackedVisual([])
        rules = RulesMap()
        assert stack.get_optimal_width(rules, 100) == 0
        assert stack.get_minimal_width(rules) == 0
        assert stack.get_height(rules, 100) == 0
        assert stack.render_strips(40, None, Style(), VISUAL_OPTIONS) == []
        assert stack.multiline is False


class TestRenderReturnsVisuals:
    async def test_the_panel_render_is_a_visual(self, tmp_path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path, active_name="work")
        async with app.run_test(size=(120, 24)) as pilot:
            await settle_workers(pilot)
            render = app.screen.query_one(AccountsPanel).render()
            assert isinstance(render, Visual)
            assert "● active" in visual_plain(render, 120)

    async def test_the_card_render_is_a_visual(self, tmp_path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path, active_name="work")
        async with app.run_test(size=(120, 24)) as pilot:
            await settle_workers(pilot)
            # unmounted is fine — the render reads active_app's clock/theme
            render = AccountCard(_view("work", last_good=_snapshot())).render()
            assert isinstance(render, AccountCardVisual)
            assert "47%" in visual_plain(render, 120)

    async def test_loading_and_empty_states_still_render_text(self, tmp_path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            panel = app.screen.query_one(AccountsPanel)
            app.snapshot = None
            text = panel.render()
            assert text.plain == "loading…"
            assert str(text.style) == DARK.muted
