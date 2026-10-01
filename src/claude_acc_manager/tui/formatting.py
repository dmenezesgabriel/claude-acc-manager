"""Small display helpers shared by the TUI screens."""

import time
from datetime import datetime

from claude_acc_manager.usage.domain.services.poll_policy import SERVE_TTL_S
from claude_acc_manager.usage.domain.usage_snapshot import (
    ScopedWindow,
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
