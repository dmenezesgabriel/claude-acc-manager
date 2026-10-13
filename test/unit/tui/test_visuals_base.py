"""``Visual``/``Strip`` render path — the infrastructure under the renderers.

``_rules_key``/``_multiline`` semantics, optimal-width delegation, and the
strip cache that makes ``render()`` cheap on repeat frames.
"""

from rich.text import Text
from support.rich_asserts import (
    VISUAL_OPTIONS,
    visual_strips,
)
from support.tui_views import DARK, NOW
from support.tui_views import account_view as _view
from support.tui_views import usage_snapshot as _snapshot
from textual.content import Content
from textual.css.styles import RulesMap
from textual.geometry import Offset
from textual.selection import Selection
from textual.strip import Strip
from textual.style import Style
from textual.visual import RenderOptions, Visual

from claude_acc_manager.tui.visuals import (
    _STRIPS,
    MiniAccountVisual,
    StackedVisual,
    _ContentVisual,
    _multiline,
    _rules_key,
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
