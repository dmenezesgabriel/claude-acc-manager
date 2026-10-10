"""The ``Visual``/``Strip`` render path — cached strips behind render().

Each card visual composes a header line with one ``UsageBarVisual`` per
usage window; the panel stacks cards and minis, leaving a blank strip only
around multi-line blocks — the exact semantics the old ``_join_blocks``
text join had.
"""

from datetime import UTC, datetime

from rich.text import Text
from support.rich_asserts import (
    VISUAL_OPTIONS,
    strip_style_at,
    visual_plain,
    visual_strips,
    visual_style_at,
)
from support.tui_app import settle_workers, wired_app
from support.use_cases import make_account
from textual.content import Content
from textual.css.styles import RulesMap
from textual.geometry import Offset
from textual.selection import Selection
from textual.strip import Strip
from textual.style import Style
from textual.visual import RenderOptions, Visual

from claude_acc_manager.accounts.application.use_cases.collect_accounts_view import (
    AccountView,
)
from claude_acc_manager.accounts.domain.entities import Account
from claude_acc_manager.tui.theme import CAM_DARK, CAM_LIGHT, Palette
from claude_acc_manager.tui.visuals import (
    _STRIPS,
    AccountCardVisual,
    MiniAccountVisual,
    StackedVisual,
    UsageBarVisual,
    _ContentVisual,
    _multiline,
    _rules_key,
)
from claude_acc_manager.tui.widgets import AccountCard, AccountsPanel
from claude_acc_manager.usage.domain.usage_cache_entry import UsageCacheEntry
from claude_acc_manager.usage.domain.usage_snapshot import (
    UsageSnapshot,
    UsageWindow,
)

DARK = Palette.from_theme(CAM_DARK)
LIGHT = Palette.from_theme(CAM_LIGHT)
NOW = 1_800_000_000.0


def _iso(epoch_s: float) -> str:
    """The ``resets_at`` wire shape for a known epoch."""
    return datetime.fromtimestamp(epoch_s, tz=UTC).isoformat()


def _view(
    name: str = "work",
    *,
    is_active: bool = False,
    is_quarantined: bool = False,
    enabled: bool = True,
    last_good: UsageSnapshot | None = None,
    fetched_at_s: float | None = NOW,
    last_error: str | None = None,
) -> AccountView:
    """An AccountView with the usage fields the renderers read."""
    account = make_account(name)
    if not enabled:
        account = Account(
            name=account.name,
            email=account.email,
            account_uuid=account.account_uuid,
            organization_uuid=account.organization_uuid,
            organization_name=account.organization_name,
            added_at=account.added_at,
            enabled=False,
        )
    return AccountView(
        account=account,
        is_active=is_active,
        is_quarantined=is_quarantined,
        has_credentials=True,
        usage=UsageCacheEntry(
            last_good=last_good,
            fetched_at_s=fetched_at_s,
            consecutive_failures=0,
            last_error=last_error,
            backoff_until_s=None,
            last_429_at_s=None,
            next_poll_at_s=None,
            poll_interval_s=None,
        ),
    )


def _snapshot(
    five_hour: float | None = 47.0,
    seven_day: float | None = 63.0,
) -> UsageSnapshot:
    """A snapshot with the standard two windows."""
    return UsageSnapshot(
        five_hour=None
        if five_hour is None
        else UsageWindow(pct=five_hour, resets_at=_iso(NOW + 7980)),
        seven_day=None
        if seven_day is None
        else UsageWindow(pct=seven_day, resets_at=_iso(NOW + 500_000)),
        scoped=(),
    )


class _WidthEcho:
    """``get_optimal_width`` echoes the container it is given — a delegation spy."""

    def get_optimal_width(self, rules: RulesMap, container_width: int) -> int:
        return container_width


class _WidthEchoVisual(Visual):
    """A part whose optimal width is the container it is handed."""

    def render_strips(
        self, width: int, height: int | None, style: Style, options: RenderOptions
    ) -> list[Strip]:
        return []

    def get_optimal_width(self, rules: RulesMap, container_width: int) -> int:
        return container_width

    def get_height(self, rules: RulesMap, width: int) -> int:
        return 1


class TestRulesKey:
    def test_default_rules_produce_the_default_key(self) -> None:
        assert _rules_key(RulesMap()) == ("left", "fold", "wrap", 0)

    def test_each_render_rule_reaches_the_key(self) -> None:
        rules = RulesMap(
            {
                "text_align": "right",
                "text_overflow": "ellipsis",
                "text_wrap": "nowrap",
                "line_pad": 2,
            }
        )
        assert _rules_key(rules) == ("right", "ellipsis", "nowrap", 2)


class TestMultilineFlag:
    def test_a_part_without_a_multiline_flag_counts_as_single_line(self) -> None:
        # Content, like the Visual base, defines no multiline flag at all
        assert _multiline(Content("plain")) is False


class TestOptimalWidthDelegation:
    def test_content_visual_forwards_the_container_width(self) -> None:
        visual = _ContentVisual(Text("x"))
        visual._content = _WidthEcho()
        assert visual.get_optimal_width(RulesMap(), 7) == 7

    def test_a_stack_forwards_the_container_width_to_its_parts(self) -> None:
        stack = StackedVisual([_WidthEchoVisual()])
        assert stack.get_optimal_width(RulesMap(), 9) == 9


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


class TestStripCache:
    def test_the_cache_key_snapshots_text_and_base_style(self) -> None:
        visual = _ContentVisual(Text("x", style="bold"))
        assert visual._key == ("x", "bold", ())

    def test_a_cache_miss_renders_then_reuses_the_stored_strips(self) -> None:
        _STRIPS.clear()
        visual = _ContentVisual(Text("miss\nbranch"))
        first = visual.render_strips(40, 1, Style(), VISUAL_OPTIONS)
        assert [strip.text.rstrip() for strip in first] == ["miss"]
        assert visual.render_strips(40, 1, Style(), VISUAL_OPTIONS) is first

    def test_a_post_style_render_respects_width_and_height(self) -> None:
        visual = _ContentVisual(Text("one\ntwo"))
        options = RenderOptions(
            get_style=lambda _style: Style(),
            rules=RulesMap(),
            post_style=Style.parse("bold"),
        )
        strips = visual.render_strips(40, 1, Style(), options)
        assert len(strips) == 1
        assert strips[0].text.startswith("one")

    def test_identical_renders_share_the_same_strips(self) -> None:
        visual = MiniAccountVisual(
            _view("work", last_good=_snapshot()), NOW, palette=DARK, redact=False
        )
        first = visual_strips(visual, 100)
        second = visual_strips(visual, 100)
        assert first is second

    def test_two_visuals_with_identical_output_share_strips(self) -> None:
        a = MiniAccountVisual(_view("work", last_good=_snapshot()), NOW, palette=DARK, redact=False)
        b = MiniAccountVisual(_view("work", last_good=_snapshot()), NOW, palette=DARK, redact=False)
        assert visual_strips(a, 100) is visual_strips(b, 100)

    def test_a_width_change_misses_the_cache(self) -> None:
        visual = MiniAccountVisual(
            _view("work", last_good=_snapshot()), NOW, palette=DARK, redact=False
        )
        assert visual_strips(visual, 100) is not visual_strips(visual, 60)

    def test_a_selection_render_bypasses_the_cache(self) -> None:
        visual = MiniAccountVisual(
            _view("work", last_good=_snapshot()), NOW, palette=DARK, redact=False
        )
        plain = visual_strips(visual, 100)
        options = RenderOptions(
            get_style=lambda _style: Style(),
            rules=RulesMap(),
            selection=Selection(Offset(0, 0), Offset(4, 0)),
            selection_style=Style.parse("reverse"),
        )
        selected = visual.render_strips(100, None, Style(), options)
        assert selected is not plain
        # and the plain render afterwards still hits the same cached entry
        assert visual_strips(visual, 100) is plain


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
