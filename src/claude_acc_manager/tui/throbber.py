"""The busy throbber — a muted→accent→muted sweep shown while work runs.

One full-width row, hidden until the ``-busy`` class lands. The widget
watches ``app.busy`` itself, so a screen only has to compose it; the
gradient is rebuilt per render so a theme flip repaints it for free.
"""

from __future__ import annotations

from time import monotonic
from typing import TYPE_CHECKING

from rich.color import Color as RichColor
from rich.segment import Segment
from rich.style import Style as RichStyle
from textual.color import Color, Gradient
from textual.css.styles import RulesMap
from textual.strip import Strip
from textual.style import Style
from textual.theme import Theme
from textual.visual import RenderOptions, Visual
from textual.widget import Widget

from claude_acc_manager.tui.theme import Palette

if TYPE_CHECKING:
    from collections.abc import Callable

    from claude_acc_manager.tui.app import CamApp


class ThrobberVisual(Visual):
    """One-row gradient sweep: ``character`` per cell, windowed by time."""

    def __init__(
        self,
        gradient: Gradient,
        *,
        character: str = "━",
        get_time: Callable[[], float] = monotonic,
    ) -> None:
        """Hold the gradient stops and the clock the sweep reads."""
        self.gradient = gradient
        self.character = character
        self.get_time = get_time
        self._segments: dict[tuple[int, RichColor | None], list[Segment]] = {}

    def make_segments(self, style: Style, width: int) -> list[Segment]:
        """Two gradient cycles of *width* cells — the window slides inside."""
        background = style.rich_style.bgcolor
        key = (width, background)
        cached = self._segments.get(key)
        if cached is not None:
            return cached
        segments = [
            Segment(
                self.character,
                RichStyle.from_color(
                    self.gradient.get_rich_color((offset / width) % 1),
                    background,
                ),
            )
            for offset in range(width * 2)
        ]
        self._segments[key] = segments
        return segments

    def render_strips(
        self,
        width: int,
        height: int | None,  # noqa: V107 — signature fixed by the Visual protocol
        style: Style,
        options: RenderOptions,  # noqa: V107 — signature fixed by the Visual protocol
    ) -> list[Strip]:
        """Slide the cached segment run by the fractional second."""
        segments = self.make_segments(style, width)
        offset = width - int((self.get_time() % 1.0) * width)
        return [Strip(segments[offset : offset + width])]

    def get_optimal_width(
        self,
        rules: RulesMap,  # noqa: V107 — signature fixed by the Visual protocol
        container_width: int,
    ) -> int:
        """Fill whatever row it is given."""
        return container_width

    def get_height(
        self,
        rules: RulesMap,  # noqa: V107 — signature fixed by the Visual protocol
        width: int,  # noqa: V107 — signature fixed by the Visual protocol
    ) -> int:
        """Always one row."""
        return 1


class Throbber(Widget):
    """The busy bar: invisible until ``app.busy`` lands ``-busy`` on it."""

    app: CamApp

    def on_mount(self) -> None:
        """Tick at ~15fps and mirror the app's busy flag as a class."""
        self.auto_refresh = 1 / 15
        self.watch(self.app, "busy", self._on_busy)

    def _on_busy(self, busy: bool) -> None:
        """Show while an action worker is in flight, hide after."""
        self.set_class(busy, "-busy")

    def render(self) -> ThrobberVisual:
        """The sweep in the current theme's muted/accent."""
        return _sweep_visual(self.app.current_theme)


def _sweep_visual(theme: Theme) -> ThrobberVisual:
    """The muted→accent→muted sweep in the given theme's palette."""
    palette = Palette.from_theme(theme)
    gradient = Gradient.from_colors(
        Color.parse(palette.muted),
        Color.parse(palette.accent),
        Color.parse(palette.muted),
    )
    return ThrobberVisual(gradient)


class LoadingBar(Widget):
    """The branded ``.loading`` cover — the sweep with no busy gate.

    Not a ``Throbber`` subclass on purpose: Textual dispatches ``on_mount``
    to every class in the MRO and CSS type selectors match every name in
    ``_css_type_names``, so a subclass would still wire ``app.busy`` and
    pick up ``visibility: hidden`` — the cover must do neither.
    """

    app: CamApp

    def on_mount(self) -> None:
        """Tick at ~15fps; the cover is always visible, so it always sweeps."""
        self.auto_refresh = 1 / 15

    def render(self) -> ThrobberVisual:
        """The sweep in the current theme's muted/accent."""
        return _sweep_visual(self.app.current_theme)
