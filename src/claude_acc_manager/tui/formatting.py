"""Small display helpers and pure ``Text`` builders shared by the TUI.

``bar_cells``/``usage_bar`` are custom renderers rather than Textual's
``ProgressBar`` because the design needs three things the stock widget
doesn't do: a severity color ramp, an optional threshold tick mark (the
auto-switch trigger line), and stale-measurement dimming.
"""

import time
from datetime import datetime

from rich.text import Text

from claude_acc_manager.accounts.application.use_cases.collect_accounts_view import (
    AccountView,
)
from claude_acc_manager.accounts.domain.entities import Account
from claude_acc_manager.tui.theme import CAM_DARK, Palette
from claude_acc_manager.usage.domain.services.pace import compute_pace
from claude_acc_manager.usage.domain.services.poll_policy import (
    SERVE_TTL_S,
    TRUST_MAX_AGE_S,
)
from claude_acc_manager.usage.domain.usage_snapshot import (
    ScopedWindow,
    UsageSnapshot,
    UsageWindow,
)


def format_duration(seconds: float) -> str:
    """Compact duration: "45s", "12m", "2h 13m", "3d 4h".

    Example:
        format_duration(7980) == "2h 13m"
    """
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        h, m = divmod(s // 60, 60)
        return f"{h}h {m}m" if m else f"{h}h"
    d, h = divmod(s // 3600, 24)
    return f"{d}d {h}h" if h else f"{d}d"


def _reset_local(window: UsageWindow | ScopedWindow | None) -> datetime | None:
    """A window's reset instant in local time, or None when unknown/invalid."""
    if window is None or not window.resets_at:
        return None
    try:
        # "Z" suffix is the wire shape; fromisoformat reads it on our 3.12 pin.
        reset = datetime.fromisoformat(window.resets_at)
    except ValueError:
        return None
    return reset.astimezone()


def reset_text(window: UsageWindow | ScopedWindow | None, now: float) -> str | None:
    """Live countdown to a window's reset ("resets 2h 13m"), or None.

    Recomputed from ``resets_at`` at render time — the countdown the API
    sent was correct at fetch time and drifts as the measurement ages.

    Example:
        reset_text(window, now_s) == "resets 45m"
    """
    reset_local = _reset_local(window)
    if reset_local is None:
        return None
    remaining = reset_local.timestamp() - now
    if remaining <= 0:
        return "resets now"
    return f"resets {format_duration(remaining)}"


def reset_clock(window: UsageWindow | ScopedWindow | None, now: float) -> str | None:
    """Absolute local reset time: "20:39" same-day, else "May 24 08:59".

    None once the reset has elapsed — "resets now" needs no clock.

    Example:
        reset_clock(window, now_s) == "20:39"
    """
    reset_local = _reset_local(window)
    if reset_local is None or reset_local.timestamp() <= now:
        return None
    now_local = datetime.fromtimestamp(now).astimezone()
    if reset_local.date() == now_local.date():
        return reset_local.strftime("%H:%M")
    return reset_local.strftime(f"%b {reset_local.day} %H:%M")


def format_age(age_s: float | None) -> str | None:
    """Measurement age note ("· 2m ago"); None while comfortably fresh.

    Example:
        format_age(7200) == "· 2h ago"
    """
    if age_s is None or age_s < SERVE_TTL_S:
        return None
    return f"· {format_duration(age_s)} ago"


def clock_stamp(now: float) -> str:
    """HH:MM:SS local-time stamp for the event log.

    Takes the epoch so callers stay on the injected clock.

    Example:
        clock_stamp(now_s) == "20:39:07"
    """
    return time.strftime("%H:%M:%S", time.localtime(now))


_BAR_FILLED = "━"
_BAR_HALF = "╸"
_BAR_EMPTY = "─"
_BAR_TICK = "┃"

_DEFAULT_PALETTE = Palette.from_theme(CAM_DARK)

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


def measurement_age_s(view: AccountView, now: float) -> float | None:
    """Seconds since the usage measurement, or None when never fetched.

    Example:
        ``measurement_age_s(view, now) == now - view.usage.fetched_at_s``
    """
    if view.usage.fetched_at_s is None:
        return None
    return now - view.usage.fetched_at_s


def measurement_is_stale(view: AccountView, now: float) -> bool:
    """Old enough that the numbers can no longer be trusted for decisions.

    Example:
        ``measurement_is_stale(view, now)`` — True past ``TRUST_MAX_AGE_S``.
    """
    age_s = measurement_age_s(view, now)
    return age_s is not None and age_s > TRUST_MAX_AGE_S


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


def email_fragment(account: Account, *, redact: bool) -> str:
    """`` (user@example.com)`` suffix, or ``""`` — the one privacy-aware join.

    Redaction drops the whole address rather than masking part of it: a
    screenshot must carry no recoverable substring. Absent emails collapse
    to the same empty fragment, so callers never branch on either state.

    Example:
        ``email_fragment(account, redact=False)`` → ``" (user@example.com)"``
    """
    if redact or not account.email:
        return ""
    return f" ({account.email})"


def _mini_header(view: AccountView, palette: Palette, *, redact: bool) -> Text:
    """``name (email)  (disabled)   `` — the fixed prefix of a mini line."""
    account = view.account
    text = Text(no_wrap=True, overflow="ellipsis")
    text.append(f"{account.name.value}", style=f"bold {palette.accent}")
    fragment = email_fragment(account, redact=redact)
    if fragment:
        text.append(fragment, style=palette.foreground)
    if not account.enabled:
        text.append("  (disabled)", style=palette.muted)
    text.append("   ")
    return text


def mini_account_text(
    view: AccountView, now: float, *, palette: Palette = _DEFAULT_PALETTE, redact: bool
) -> Text:
    """One minimized line for an inactive account.

    ``work (user@example.com)   5h 92% · 7d 63%`` — pcts only, severity
    colored; a window at/over 100% brings its reset countdown along, and a
    maxed per-model window shows as ``Fable (!)``. Quarantined lineages
    show their badge instead — the numbers cannot refresh.
    """
    text = _mini_header(view, palette, redact=redact)
    if view.is_quarantined:
        text.append("⚠ quarantined", style=palette.sev_warn)
        return text
    parts = _mini_usage_parts(view, now, measurement_is_stale(view, now), palette)
    if not parts:
        text.append("usage unknown", style=palette.muted)
        return text
    for i, part in enumerate(parts):
        if i:
            text.append(" · ", style=palette.track)
        text.append(part)
    return text
