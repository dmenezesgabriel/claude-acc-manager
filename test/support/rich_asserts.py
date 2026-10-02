"""Style-spans assertions for Rich ``Text`` and Textual ``Strip`` objects.

Rich merge adjacent same-style runs, so tests pin *coverage* — the style
covering a character offset — rather than exact span boundaries. The
``Strip`` variant does the same for rendered log lines, whose styles only
exist on ``Segment`` objects.
"""

from rich.text import Text
from textual.strip import Strip


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
