"""Style-spans assertions for Rich ``Text`` and Textual ``Strip`` objects.

Rich merge adjacent same-style runs, so tests pin *coverage* — the style
covering a character offset — rather than exact span boundaries. The
``Strip`` variant does the same for rendered log lines, whose styles only
exist on ``Segment`` objects.
"""

from rich.text import Text
from textual.css.styles import RulesMap
from textual.strip import Strip
from textual.style import Style
from textual.visual import RenderOptions, Visual

# The widget-free render contract: no app console, no rules, no selection.
VISUAL_OPTIONS = RenderOptions(get_style=lambda _style: Style(), rules=RulesMap())


def visual_strips(visual: Visual, width: int = 80) -> list[Strip]:
    """Render a ``Visual`` at ``width`` with a null base style."""
    return visual.render_strips(width, None, Style(), VISUAL_OPTIONS)


def visual_plain(visual: Visual, width: int = 80) -> str:
    """The visual's strips rejoined as flat text — what ``Text.plain`` was.

    Strips pad to ``width``; the rstrip drops that pad, matching the
    un-padded ``Text.plain`` shape the renderers used to return.

    Example:
        ``visual_plain(MiniAccountVisual(view, now)) == mini.plain``
    """
    return "\n".join(strip.text.rstrip() for strip in visual_strips(visual, width))


def visual_style_at(visual: Visual, offset: int, width: int = 80) -> str:
    """The style covering ``offset`` in the visual's ``visual_plain`` text."""
    pos = 0
    for strip in visual_strips(visual, width):
        line = strip.text.rstrip()
        if pos <= offset < pos + len(line):
            return strip_style_at(strip, offset - pos)
        pos += len(line) + 1  # the rejoin consumed one "\n" per line
    return ""


def visual_span_styles(visual: Visual, width: int = 80) -> list[str]:
    """Every segment style across all strips — the ``Text.spans`` analog."""
    return [str(seg.style) for strip in visual_strips(visual, width) for seg in strip if seg.style]


def span_styles(text: Text) -> list[str]:
    """The style string of every span in a Rich ``Text``.

    Example:
        ``span_styles(bar_cells(0.5, 4, palette)) == [sev_ok, track]``
    """
    return [str(span.style) for span in text.spans]


def text_style_at(text: Text, offset: int) -> str:
    """The style covering a character offset — spans merge adjacent runs."""
    for span in text.spans:
        if span.start <= offset < span.end:
            return str(span.style)
    return ""


def strip_style_at(strip: Strip, offset: int) -> str:
    """The style covering a character offset inside a rendered ``Strip``."""
    pos = 0
    for seg in strip:
        if pos <= offset < pos + len(seg.text):
            return str(seg.style)
        pos += len(seg.text)
    return ""
