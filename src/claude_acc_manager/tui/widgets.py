"""Shared render widgets: usage bars, account cards, and the accounts panel.

``bar_cells``/``usage_bar`` are custom renderers rather than Textual's
``ProgressBar`` because the design needs three things the stock widget
doesn't do: a severity color ramp, an optional threshold tick mark (the
auto-switch trigger line), and stale-measurement dimming.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual import getters
from textual.reactive import var
from textual.widgets import ListItem, Static

from claude_acc_manager.accounts.application.use_cases.collect_accounts_view import (
    AccountView,
)
from claude_acc_manager.tui.formatting import (
    format_age,
    reset_clock,
    reset_text,
)
from claude_acc_manager.tui.theme import CAM_DARK, Palette
from claude_acc_manager.usage.domain.services.pace import compute_pace
from claude_acc_manager.usage.domain.services.poll_policy import TRUST_MAX_AGE_S
from claude_acc_manager.usage.domain.usage_snapshot import (
    ScopedWindow,
    UsageSnapshot,
    UsageWindow,
)

if TYPE_CHECKING:
    from claude_acc_manager.tui.app import CamApp

_BAR_FILLED = "━"
_BAR_HALF = "╸"
_BAR_EMPTY = "─"
_BAR_TICK = "┃"

_DEFAULT_PALETTE = Palette.from_theme(CAM_DARK)

# The exact fallback width is unobservable: a 1px shift is invisible under the
# 30-cell bar cap and the suffix-fit check only bites at long labels.
_UNMOUNTED_WIDTH = 80

Row = tuple[str, float, str, str]
"""One usage row: ``(label, pct, suffix, suffix_full)`` — empty suffix means none."""


def _tick_index(threshold: float | None, width: int) -> int | None:
    """The bar cell carrying the threshold tick, or None when unset."""
    if threshold is None:
        return None
    return min(width - 1, max(0, round(threshold / 100.0 * width)))


def _cell(i: int, full: int, half: bool, tick_at: int | None) -> str:
    """The glyph for one bar cell — the tick wins over the fill."""
    if tick_at is not None and i == tick_at:
        return _BAR_TICK
    if i < full:
        return _BAR_FILLED
    if i == full and half:
        return _BAR_HALF
    return _BAR_EMPTY


def _cell_style(
    i: int, full: int, half: bool, tick_at: int | None, fill: str, palette: Palette
) -> str:
    """The style paired with :func:`_cell`'s glyph at the same index."""
    if tick_at is not None and i == tick_at:
        return palette.sev_warn
    if i < full or (i == full and half):
        return fill
    return palette.track


def bar_cells(
    pct: float | None,
    width: int,
    *,
    stale: bool = False,
    threshold: float | None = None,
    palette: Palette = _DEFAULT_PALETTE,
) -> Text:
    """Just the bar glyphs: severity-colored fill, track, optional tick."""
    text = Text()
    if pct is None:
        text.append(_BAR_EMPTY * width, style=palette.track)
        return text
    cells = min(max(pct, 0.0) / 100.0 * width, width)
    full = int(cells)
    half = (cells - full) >= 0.5
    tick_at = _tick_index(threshold, width)
    color = palette.severity(pct)
    fill_style = f"{color} dim" if stale else color
    for i in range(width):
        text.append(
            _cell(i, full, half, tick_at),
            style=_cell_style(i, full, half, tick_at, fill_style, palette),
        )
    return text


def usage_bar(
    label: str,
    pct: float | None,
    suffix: str | None,
    width: int,
    *,
    stale: bool = False,
    threshold: float | None = None,
    palette: Palette = _DEFAULT_PALETTE,
) -> Text:
    """One full bar line: ``5h ━━━━╸────┃──  47%  resets 2h 13m · 20:39``."""
    text = Text()
    text.append(f"{label} ", style=palette.muted)
    text.append(bar_cells(pct, width, stale=stale, threshold=threshold, palette=palette))
    if pct is None:
        text.append("  usage unknown", style=palette.muted)
    else:
        color = palette.severity(pct)
        text.append(f" {pct:3.0f}%", style=f"{color} dim" if stale else color)
    if suffix:
        text.append(f"  {suffix}", style=palette.muted)
    return text


def _reset_parts(
    window: UsageWindow | ScopedWindow | None, now: float
) -> tuple[str | None, str | None]:
    """Countdown suffix and its clock-extended variant for one window.

    ``("resets 2h 13m", "resets 2h 13m · 20:39")`` — the second form is what
    a row shows when it has the width for it. Equal when no clock is known.
    """
    reset = reset_text(window, now)
    if not reset:
        return None, None
    clock = reset_clock(window, now)
    return reset, f"{reset} · {clock}" if clock else reset


def _pace_suffix(window: UsageWindow | ScopedWindow, fetched_at_s: float | None) -> str:
    """``(ahead of pace)`` when a weekly window is meaningfully ahead, else ''."""
    result = compute_pace(window, fetched_at_s=fetched_at_s)
    return "(ahead of pace)" if result and result.ahead else ""


def _join_suffix(reset: str | None, marker: str) -> str:
    """``resets 2h 13m  (ahead of pace)`` — either side may be absent."""
    if reset and marker:
        return f"{reset}  {marker}"
    return reset or marker or ""


def _window_row(
    window: UsageWindow | None,
    label: str,
    now: float,
    fetched_at_s: float | None,
) -> Row | None:
    """One 5h/7d row; the 7d row is the only one that earns a pace marker."""
    if window is None:
        return None
    reset, reset_full = _reset_parts(window, now)
    marker = _pace_suffix(window, fetched_at_s) if label == "7d" else ""
    return (
        label,
        window.pct,
        _join_suffix(reset, marker),
        _join_suffix(reset_full, marker),
    )


def _scoped_row(window: ScopedWindow, now: float, fetched_at_s: float | None) -> Row:
    """One per-model row: a maxed window flags ``(!)``, else a pace marker."""
    reset, reset_full = _reset_parts(window, now)
    marker = "(!)" if window.pct >= 100 else _pace_suffix(window, fetched_at_s)
    return (
        window.name,
        window.pct,
        _join_suffix(reset, marker),
        _join_suffix(reset_full, marker),
    )


def usage_rows(
    snapshot: UsageSnapshot | None, now: float, fetched_at_s: float | None = None
) -> list[Row]:
    """(label, pct, suffix, suffix_full) rows in CLI order: 5h, 7d, scoped.

    ``suffix_full`` extends the reset countdown with the absolute clock time
    (``resets 2h 13m · 20:39``) for rows that have room; otherwise it equals
    ``suffix``. Only windows the account actually has produce a row.
    """
    if snapshot is None:
        return []
    rows = [
        row
        for window, label in ((snapshot.five_hour, "5h"), (snapshot.seven_day, "7d"))
        if (row := _window_row(window, label, now, fetched_at_s)) is not None
    ]
    rows.extend(_scoped_row(window, now, fetched_at_s) for window in snapshot.scoped)
    return rows


def _age_s(view: AccountView, now: float) -> float | None:
    """Seconds since the measurement, or None when never fetched."""
    if view.usage.fetched_at_s is None:
        return None
    return now - view.usage.fetched_at_s


def _is_stale(age_s: float | None) -> bool:
    """Old enough that the numbers can no longer be trusted for decisions."""
    return age_s is not None and age_s > TRUST_MAX_AGE_S


def _card_header(view: AccountView, age_s: float | None, palette: Palette) -> Text:
    """``name (email)   ● active   (disabled)   · 12m ago``."""
    account = view.account
    text = Text()
    text.append(f"{account.name.value}", style=f"bold {palette.accent}")
    if account.email:
        text.append(f" ({account.email})", style=palette.foreground)
    if view.is_active:
        text.append("   ● active", style=f"bold {palette.accent}")
    if not account.enabled:
        text.append("   (disabled)", style=palette.muted)
    age = format_age(age_s)
    if age:
        text.append(f"   {age}", style=palette.muted)
    return text


def _append_unavailable(text: Text, last_error: str | None, palette: Palette) -> None:
    """The 'usage unavailable' fallback line under a card header."""
    text.append("\n    ")
    text.append("usage unavailable", style=palette.muted)
    if last_error:
        # Same wording as the CLI detail line — the raw fetch-error kind.
        text.append(f" · {last_error}", style=palette.muted)


def _append_bar_rows(
    text: Text,
    rows: list[Row],
    width: int,
    *,
    stale: bool,
    threshold: float | None,
    palette: Palette,
) -> None:
    """One indented usage_bar line per row, clocks shown where they fit."""
    label_width = max(len(label) for label, _pct, _suffix, _full in rows)
    bar_width = max(12, min(30, width - 42 - label_width))
    # everything on a row except the suffix: indent, label, bar, " NNN%", gap
    row_overhead = 4 + label_width + 1 + bar_width + 5 + 2
    for label, pct, suffix, suffix_full in rows:
        # per-row: show the absolute clock only where it fits, so a long
        # row degrading doesn't cost the other rows their clocks
        if suffix_full != suffix and row_overhead + len(suffix_full) <= width:
            suffix = suffix_full
        text.append("\n    ")
        text.append(
            usage_bar(
                f"{label:<{label_width}}",
                pct,
                suffix,
                bar_width,
                stale=stale,
                threshold=threshold,
                palette=palette,
            )
        )


def account_card_text(
    view: AccountView,
    width: int,
    *,
    threshold: float | None = None,
    now: float,
    palette: Palette = _DEFAULT_PALETTE,
) -> Text:
    """The full account card: header line + per-window bar rows."""
    age_s = _age_s(view, now)
    text = _card_header(view, age_s, palette)
    if view.is_quarantined:
        text.append("\n    ")
        text.append("⚠ quarantined — dead refresh-token lineage", style=palette.sev_warn)
        return text
    rows = usage_rows(view.usage.last_good, now, view.usage.fetched_at_s)
    if not rows:
        _append_unavailable(text, view.usage.last_error, palette)
        return text
    _append_bar_rows(
        text,
        rows,
        width,
        stale=_is_stale(age_s),
        threshold=threshold,
        palette=palette,
    )
    return text


def _mini_window_part(
    window: UsageWindow, label: str, stale: bool, view: AccountView, now: float, palette: Palette
) -> Text:
    """``5h 92%`` (and ``(resets 30m)`` at/over 100%, ``(ahead)`` for 7d)."""
    pct = window.pct
    color = palette.severity(pct)
    segment = Text()
    segment.append(f"{label} ", style=palette.muted)
    segment.append(f"{pct:.0f}%", style=f"{color} dim" if stale else color)
    pace = _pace_suffix(window, view.usage.fetched_at_s) if label == "7d" else ""
    if pct >= 100:
        reset = reset_text(window, now)
        if reset:
            segment.append(f" ({reset})", style=palette.muted)
    elif pace:
        segment.append(" (ahead)", style=palette.sev_warn)
    return segment


def _mini_usage_parts(view: AccountView, now: float, stale: bool, palette: Palette) -> list[Text]:
    """One segment per bar-window plus ``Fable (!)`` for maxed scoped windows."""
    last_good = view.usage.last_good
    if last_good is None:
        return []
    parts = [
        _mini_window_part(window, label, stale, view, now, palette)
        for window, label in ((last_good.five_hour, "5h"), (last_good.seven_day, "7d"))
        if window is not None
    ]
    parts.extend(
        Text(f"{window.name} (!)", style=palette.sev_crit)
        for window in last_good.scoped
        if window.pct >= 100
    )
    return parts


def _mini_header(view: AccountView, palette: Palette) -> Text:
    """``name (email)  (disabled)   `` — the fixed prefix of a mini line."""
    account = view.account
    text = Text(no_wrap=True, overflow="ellipsis")
    text.append(f"{account.name.value}", style=f"bold {palette.accent}")
    if account.email:
        text.append(f" ({account.email})", style=palette.foreground)
    if not account.enabled:
        text.append("  (disabled)", style=palette.muted)
    text.append("   ")
    return text


def mini_account_text(
    view: AccountView, now: float, *, palette: Palette = _DEFAULT_PALETTE
) -> Text:
    """One minimized line for an inactive account.

    ``work (user@example.com)   5h 92% · 7d 63%`` — pcts only, severity
    colored; a window at/over 100% brings its reset countdown along, and a
    maxed per-model window shows as ``Fable (!)``. Quarantined lineages
    show their badge instead — the numbers cannot refresh.
    """
    text = _mini_header(view, palette)
    if view.is_quarantined:
        text.append("⚠ quarantined", style=palette.sev_warn)
        return text
    parts = _mini_usage_parts(view, now, _is_stale(_age_s(view, now)), palette)
    if not parts:
        text.append("usage unknown", style=palette.muted)
        return text
    for i, part in enumerate(parts):
        if i:
            text.append(" · ", style=palette.track)
        text.append(part)
    return text


def _join_blocks(blocks: list[Text]) -> Text:
    """Minis pack tight; the expanded card gets a blank line around it."""
    text = Text()
    # The initial value is dead: it is only read when i >= 1, by which
    # point a real bool has overwritten it — hence pragma: no mutate.
    previous_multiline = False  # pragma: no mutate
    for i, block in enumerate(blocks):
        multiline = "\n" in block.plain
        if i:
            text.append("\n\n" if (multiline or previous_multiline) else "\n")
        text.append(block)
        previous_multiline = multiline
    return text


class AccountsPanel(Static):
    """Static account overview: the active account full-size, others as minis.

    The dashboard's — and with ``show_minis=False`` the auto screen's —
    always-visible monitor.
    """

    app: CamApp

    def __init__(self, *, show_minis: bool = True, id: str | None = None) -> None:
        """``show_minis=False`` renders only the active card."""
        super().__init__(id=id)
        self._show_minis = show_minis

    def on_mount(self) -> None:
        """Repaint on every new snapshot or theme flip.

        watch(), not data_bind: binds source from the active message pump,
        so app-owned reactives can only be bound from app-pumped contexts —
        a deep widget's cross-node propagation is what watch() is for.
        """
        self.watch(self.app, "snapshot", self._repaint)
        self.watch(self.app, "theme", self._repaint)

    def _repaint(self, *_args: object) -> None:
        """Watcher-shaped repaint — watch callbacks arrive as (old, new)."""
        self.refresh(layout=True)

    def render(self) -> Text:
        """Paint the frame: loading, empty, or card + minis."""
        app = self.app
        palette = Palette.from_theme(app.current_theme)
        snap = app.snapshot
        if snap is None:
            return Text("loading…", style=palette.muted)
        if not snap.accounts:
            return Text(
                "No managed accounts yet.\nRun `cam add <name>` to register one.",
                style=palette.muted,
            )
        blocks = self._blocks(snap.accounts, app.now_s(), app.threshold_pct, palette)
        if not blocks:
            return Text("no active managed login", style=palette.muted)
        return _join_blocks(blocks)

    def _blocks(
        self,
        accounts: tuple[AccountView, ...],
        now: float,
        threshold: float,
        palette: Palette,
    ) -> list[Text]:
        """Active account's card first, then one mini per inactive row."""
        width = self.size.width or _UNMOUNTED_WIDTH
        blocks: list[Text] = []
        for row in accounts:
            if row.is_active:
                blocks.append(
                    account_card_text(row, width, threshold=threshold, now=now, palette=palette)
                )
            elif self._show_minis:
                blocks.append(mini_account_text(row, now, palette=palette))
        return blocks


class AccountCard(Static):
    """One account rendered full-size (used by the switch screen's list)."""

    app: CamApp

    view: var[AccountView | None] = var(None)

    def __init__(self, view: AccountView, *, threshold: float | None = None) -> None:
        """Hold the row and the auto-switch threshold tick."""
        super().__init__()
        self.view = view
        self._threshold = threshold

    def watch_view(self) -> None:
        """A bound ``view`` change repaints the card."""
        self.refresh(layout=True)

    def render(self) -> Text:
        """Paint the card at the current width and theme."""
        app = self.app
        view = self.view
        if view is None:
            # can't happen: the ctor seeds a view before the card can render —
            # the var's default exists only because reactive defaults are
            # class-level
            return Text()
        return account_card_text(
            view,
            self.size.width or _UNMOUNTED_WIDTH,
            threshold=self._threshold,
            now=app.now_s(),
            palette=Palette.from_theme(app.current_theme),
        )


class AccountItem(ListItem):
    """ListView row wrapping an :class:`AccountCard`; remembers its account."""

    card = getters.query_one(AccountCard)

    view: var[AccountView | None] = var(None)

    def __init__(self, view: AccountView) -> None:
        """Store the row's identity for selection handling."""
        # the mount-time bind re-syncs card.view; the ctor seed only covers
        # the pre-bind render window a mounted row never reaches — the
        # AccountCard(None) mutant is equivalent, hence pragma: no mutate
        super().__init__(AccountCard(view))  # pragma: no mutate
        self.set_account(view)

    def on_mount(self) -> None:
        """Bind the card's ``view`` to the row's — set_account flows through."""
        self.card.data_bind(view=AccountItem.view)

    def set_account(self, view: AccountView) -> None:
        """Refresh the stored identity; the bound card follows ``view``."""
        self.account_name = view.account.name
        self.view = view


class ChromeStatic(Static):
    """A Static that refuses text selection — titles, badges, hints."""

    ALLOW_SELECT = False


class MenuItem(ListItem):
    """One menu row: a label, an action id, an optional accelerator key."""

    ALLOW_SELECT = False

    def __init__(
        self, label: str, action_id: str, *, muted: bool = False, key: str | None = None
    ) -> None:
        """Wrap the label in a Static; ``muted`` dims it, ``key`` prefixes it."""
        text = f"{key}  {label}" if key else label
        # markup=None is falsy through visualize()'s ``if markup`` check —
        # identical to False, hence pragma: no mutate.
        item = ChromeStatic(text, markup=False)  # pragma: no mutate
        if muted:
            item.add_class("menu-item-muted")
        super().__init__(item)
        self.action_id = action_id
        self.key = key
