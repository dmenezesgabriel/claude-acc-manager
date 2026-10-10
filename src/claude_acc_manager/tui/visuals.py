"""Strip-cached ``Visual`` renderers for the account monitor.

Widgets build these visuals per repaint; the shared ``_STRIPS`` cache keys
the ``Content`` → ``Strip`` expansion on the rendered glyphs, styles, and
geometry, so a poll tick that changes nothing on screen never re-walks
segments. Selection renders bypass the cache — they vary per keystroke.
"""

from __future__ import annotations

from collections.abc import Iterable

from rich.text import Text
from textual.cache import LRUCache
from textual.content import Content
from textual.css.styles import RulesMap
from textual.strip import Strip
from textual.style import Style
from textual.visual import RenderOptions, Visual

from claude_acc_manager.accounts.application.use_cases.collect_accounts_view import (
    AccountView,
)
from claude_acc_manager.tui.formatting import (
    Row,
    email_fragment,
    format_age,
    measurement_age_s,
    measurement_is_stale,
    mini_account_text,
    usage_bar,
    usage_rows,
)
from claude_acc_manager.tui.theme import Palette

# One entry per distinct (glyphs, styles, geometry) — generous for every
# width the layout can produce across a session's repaints.
_CACHE_MAX = 128

_STRIPS: LRUCache[tuple[object, ...], list[Strip]] = LRUCache(maxsize=_CACHE_MAX)

# The wrap/pad rules that change a Content's rendered strips, with the
# defaults Textual applies when a rule is absent.
_RULE_DEFAULTS = {"text_align": "left", "text_overflow": "fold", "text_wrap": "wrap", "line_pad": 0}


def _rules_key(rules: RulesMap) -> tuple[object, ...]:
    """The wrap/pad rules that change a Content's rendered strips."""
    plain = dict(rules)
    return tuple(plain.get(name, _RULE_DEFAULTS[name]) for name in _RULE_DEFAULTS)


def _multiline(part: Visual) -> bool:
    """True when the part's own text spans lines — the pre-wrap join flag."""
    # pragma: no mutate justification: under ``is True`` any falsy default
    # reads identically, so False/None swaps are unobservable.
    return getattr(part, "multiline", False) is True  # pragma: no mutate


class _ContentVisual(Visual):
    """One Rich ``Text`` body expanded to strips once per width/style combo.

    Sizing delegates to the inner ``Content`` — identical to the visual
    ``visualize()`` builds when a widget's ``render()`` returns ``Text``.
    """

    def __init__(self, text: Text) -> None:
        """Snapshot the cache key and convert once at build time."""
        self._key = (text.plain, str(text.style), tuple(text.spans))
        self._content = Content.from_rich_text(text)

    @property
    def multiline(self) -> bool:
        """True when the wrapped text carries a literal newline."""
        return "\n" in self._content.plain

    def render_strips(
        self, width: int, height: int | None, style: Style, options: RenderOptions
    ) -> list[Strip]:
        """Serve strips from ``_STRIPS``; selection renders never cache."""
        if options.selection is not None or options.post_style is not None:
            return self._content.render_strips(width, height, style, options)
        key = (*self._key, width, height, style, *_rules_key(options.rules))
        strips = _STRIPS.get(key)
        if strips is None:
            strips = self._content.render_strips(width, height, style, options)
            _STRIPS[key] = strips
        return strips

    def get_optimal_width(self, rules: RulesMap, container_width: int) -> int:
        """The widest line — delegated to the inner Content's own cache."""
        return self._content.get_optimal_width(rules, container_width)

    def get_minimal_width(self, rules: RulesMap) -> int:
        """The widest single word — delegated to the inner Content."""
        return self._content.get_minimal_width(rules)

    def get_height(self, rules: RulesMap, width: int) -> int:
        """Rendered line count at ``width`` — delegated to the Content."""
        return self._content.get_height(rules, width)


class StackedVisual(Visual):
    """Parts stacked vertically — the account-block join in visual form.

    ``pad_multiline`` mirrors the old text join: a block on either side of
    a boundary being multi-line earns one blank strip; card interiors pass
    False because a card's own lines always join directly.

    Example:
        ``StackedVisual([card_visual, mini_visual])`` paints the card, a
        blank strip, then the mini.
    """

    def __init__(self, parts: Iterable[Visual], *, pad_multiline: bool = True) -> None:
        """Keep the ordered parts; join semantics live on the flag."""
        self._parts = list(parts)
        self._pad_multiline = pad_multiline

    @property
    def multiline(self) -> bool:
        """True when joined parts produce more than one line of text."""
        return len(self._parts) > 1 or any(_multiline(part) for part in self._parts)

    def _needs_separator(self, i: int) -> bool:
        """A boundary earns a blank strip when either neighbour is multi-line."""
        return (
            i > 0
            and self._pad_multiline
            and (_multiline(self._parts[i]) or _multiline(self._parts[i - 1]))
        )

    def render_strips(
        self, width: int, height: int | None, style: Style, options: RenderOptions
    ) -> list[Strip]:
        """Render each part at ``width``, inserting blank-strip separators."""
        strips: list[Strip] = []
        for i, part in enumerate(self._parts):
            if self._needs_separator(i):
                strips.append(Strip.blank(width, style.rich_style))
            strips.extend(part.render_strips(width, None, style, options))
        if height is not None:
            return strips[:height]
        return strips

    def get_optimal_width(self, rules: RulesMap, container_width: int) -> int:
        """The widest part — a stack never adds horizontal extent."""
        return max(
            (part.get_optimal_width(rules, container_width) for part in self._parts),
            default=0,
        )

    def get_minimal_width(self, rules: RulesMap) -> int:
        """The widest part's minimal width — a stack's floor is its widest."""
        return max((part.get_minimal_width(rules) for part in self._parts), default=0)

    def get_height(self, rules: RulesMap, width: int) -> int:
        """Sum of part heights at ``width`` plus separator strips."""
        total = 0
        for i, part in enumerate(self._parts):
            if self._needs_separator(i):
                total += 1
            total += part.get_height(rules, width)
        return total


class UsageBarVisual(_ContentVisual):
    """One indented usage-bar row: ``    5h ━━━━╸──┃───  47%  resets 2h``.

    Example:
        ``UsageBarVisual("5h", 47.0, "resets 2h 13m", 24, palette=palette)``
    """

    def __init__(
        self,
        label: str,
        pct: float | None,
        suffix: str | None,
        width: int,
        *,
        stale: bool = False,
        threshold: float | None = None,
        palette: Palette,
    ) -> None:
        """Build the indented ``usage_bar`` text and wrap it for caching."""
        text = Text("    ")
        text.append_text(
            usage_bar(
                label,
                pct,
                suffix,
                width,
                stale=stale,
                threshold=threshold,
                palette=palette,
            )
        )
        super().__init__(text)


class MiniAccountVisual(_ContentVisual):
    """One minimized inactive-account line — ``name (email)   5h 92%``.

    Example:
        ``MiniAccountVisual(view, now, palette=palette)``
    """

    def __init__(self, view: AccountView, now: float, *, palette: Palette, redact: bool) -> None:
        """Build ``mini_account_text`` and wrap it for caching."""
        super().__init__(mini_account_text(view, now, palette=palette, redact=redact))


def _card_header(view: AccountView, now: float, palette: Palette, *, redact: bool) -> Text:
    """``name (email)   ● active   (disabled)   · 12m ago``."""
    account = view.account
    text = Text()
    text.append(f"{account.name.value}", style=f"bold {palette.accent}")
    fragment = email_fragment(account, redact=redact)
    if fragment:
        text.append(fragment, style=palette.foreground)
    if view.is_active:
        text.append("   ● active", style=f"bold {palette.accent}")
    if not account.enabled:
        text.append("   (disabled)", style=palette.muted)
    age = format_age(measurement_age_s(view, now))
    if age:
        text.append(f"   {age}", style=palette.muted)
    return text


def _unavailable_text(last_error: str | None, palette: Palette) -> Text:
    """The indented 'usage unavailable' fallback line under a card header."""
    text = Text("    ")
    text.append("usage unavailable", style=palette.muted)
    if last_error:
        # Same wording as the CLI detail line — the raw fetch-error kind.
        text.append(f" · {last_error}", style=palette.muted)
    return text


def _quarantined_text(palette: Palette) -> Text:
    """The indented quarantine warning under a card header."""
    text = Text("    ")
    text.append("⚠ quarantined — dead refresh-token lineage", style=palette.sev_warn)
    return text


def _fitted_suffix(suffix: str, suffix_full: str, overhead: int, width: int) -> str:
    """The clock-extended suffix where the row has room.

    A long row degrading doesn't cost the other rows their clocks — the
    fit check runs per row, not per card.
    """
    if suffix_full != suffix and overhead + len(suffix_full) <= width:
        return suffix_full
    return suffix


def _bar_visuals(
    rows: list[Row],
    width: int,
    *,
    stale: bool,
    threshold: float | None,
    palette: Palette,
) -> list[UsageBarVisual]:
    """One indented bar visual per row, clocks shown where they fit."""
    label_width = max(len(label) for label, _pct, _suffix, _full in rows)
    bar_width = max(12, min(30, width - 42 - label_width))
    # everything on a row except the suffix: indent, label, bar, " NNN%", gap
    row_overhead = 4 + label_width + 1 + bar_width + 5 + 2
    return [
        UsageBarVisual(
            f"{label:<{label_width}}",
            pct,
            _fitted_suffix(suffix, suffix_full, row_overhead, width),
            bar_width,
            stale=stale,
            threshold=threshold,
            palette=palette,
        )
        for label, pct, suffix, suffix_full in rows
    ]


def _card_body(
    view: AccountView, width: int, *, threshold: float | None, now: float, palette: Palette
) -> list[Visual]:
    """Everything under the card header: warning, fallback, or bar rows."""
    if view.is_quarantined:
        return [_ContentVisual(_quarantined_text(palette))]
    rows = usage_rows(view.usage.last_good, now, view.usage.fetched_at_s)
    if not rows:
        return [_ContentVisual(_unavailable_text(view.usage.last_error, palette))]
    bars: list[Visual] = [
        *_bar_visuals(
            rows,
            width,
            stale=measurement_is_stale(view, now),
            threshold=threshold,
            palette=palette,
        )
    ]
    return bars


class AccountCardVisual(StackedVisual):
    """The full account card: header line + one ``UsageBarVisual`` per row.

    Example:
        ``AccountCardVisual(view, 80, threshold=90.0, now=now, palette=palette)``
    """

    def __init__(
        self,
        view: AccountView,
        width: int,
        *,
        threshold: float | None = None,
        now: float,
        palette: Palette,
        redact: bool,
    ) -> None:
        """Compose the header and body parts into the card's stack."""
        parts: list[Visual] = [_ContentVisual(_card_header(view, now, palette, redact=redact))]
        parts.extend(_card_body(view, width, threshold=threshold, now=now, palette=palette))
        # a card's own lines join directly — the blank-line rule is only
        # for separation between sibling blocks on the panel
        super().__init__(parts, pad_multiline=False)
