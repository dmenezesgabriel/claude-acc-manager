"""Human rendering for ``cam auto`` — one severity-colored line per event.

The engine emits typed ``AutoEvent``s; this module owns the human transport:
a whole-line style per kind (green movement, red hard outcomes, yellow
quarantine, dim routine), except ``poll`` whose used-pct segment rides the
shared WARN/CRIT ramp. ``--json`` never reaches these builders — the JSONL
sink serializes wire payloads byte-identical to before.

Example:
    emit = auto_emit(json_mode=False, clock=clock, out=out)
    emit(SwitchEvent(trigger="proactive", from_name="x", to_name="y"))
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from typing import TYPE_CHECKING

from claude_acc_manager.auto.domain.auto_event import (
    AllExhaustedEvent,
    AutoEvent,
    ErrorEvent,
    NoSwitchEvent,
    PollEvent,
    QuarantinedEvent,
    SleepEvent,
    SwitchEvent,
)
from claude_acc_manager.cli.human import HumanOutput
from claude_acc_manager.cli.json_output import auto_event_json
from claude_acc_manager.settings.domain.settings_spec import AutoSettings
from claude_acc_manager.usage.application.ports import ClockPort

if TYPE_CHECKING:
    from rich.text import Text


def auto_emit(json_mode: bool, clock: ClockPort, out: HumanOutput) -> Callable[[AutoEvent], None]:
    """The event sink — JSONL one-per-line, or styled human text."""
    if json_mode:
        return lambda event: print(
            json.dumps(auto_event_json(event, _iso(clock.now_epoch_s()))), flush=True
        )
    return lambda event: out.print(render_event(clock, event, out))


def banner_text(settings: AutoSettings, dry_run: bool) -> Text:
    """The loop's startup line — bold chrome so it reads as a header."""
    from rich.text import Text

    return Text(
        f"auto-switch running: threshold {settings.threshold:g}%, "
        f"every {settings.interval_seconds:g}s"
        f"{' (dry-run)' if dry_run else ''} — Ctrl-C to stop",
        style="bold",
    )


def render_event(clock: ClockPort, event: AutoEvent, out: HumanOutput) -> str | Text:
    """One ``{stamp}  {line}`` row — styled by kind, plain when unmapped."""
    stamp = f"{_stamp(clock)}  "
    if isinstance(event, PollEvent):
        return _poll_text(stamp, event, out)
    style = out.event_style(event.kind)
    if style is None:
        return f"{stamp}{_event_line(event)}"
    from rich.text import Text

    return Text(f"{stamp}{_event_line(event)}", style=style)


def _iso(epoch_s: float) -> str:
    """ISO-8601 UTC seconds stamp — the JSONL ``ts``/reset rendering."""
    return (
        dt.datetime.fromtimestamp(epoch_s, dt.UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _stamp(clock: ClockPort) -> str:
    """The HH:MM:SS line prefix — UTC so tests stay hermetic."""
    return dt.datetime.fromtimestamp(clock.now_epoch_s(), dt.UTC).strftime("%H:%M:%S")


def _event_line(event: AutoEvent) -> str:
    """One human line per event kind."""
    if isinstance(event, SwitchEvent):
        return _switch_line(event)
    if isinstance(event, NoSwitchEvent):
        return _no_switch_line(event)
    if isinstance(event, QuarantinedEvent):
        return _quarantined_line(event)
    if isinstance(event, AllExhaustedEvent):
        return _exhausted_line(event)
    if isinstance(event, SleepEvent):
        return _sleep_line(event)
    if isinstance(event, ErrorEvent):
        return _error_line(event)
    return event.kind


def _switch_line(event: SwitchEvent) -> str:
    verb = "[dry-run] would switch" if event.dry_run else "Switched"
    # pragma: no mutate justification: the or-arms are None-defense for wire
    # fields the engine always fills — unreachable in every emit path.
    source = event.from_name or "(none)"  # pragma: no mutate
    target = event.to_name or "?"  # pragma: no mutate
    return f"{verb} {source} -> {target} ({event.trigger})"


def _no_switch_line(event: NoSwitchEvent) -> str:
    suffix = f" ({event.detail})" if event.detail else ""
    return f"no switch: {event.reason}{suffix}"


def _quarantined_line(event: QuarantinedEvent) -> str:
    return (
        f"{event.name} quarantined: {event.reason}. "
        f"Log in with it and run 'cam add {event.name}' to recover."
    )


def _exhausted_line(event: AllExhaustedEvent) -> str:
    if event.earliest_reset_at_s is not None:
        return f"all accounts exhausted; earliest reset {_iso(event.earliest_reset_at_s)}"
    return "all accounts exhausted; no reset time known"


def _sleep_line(event: SleepEvent) -> str:
    return f"sleeping {event.seconds / 60:.0f}m (until {event.until})"


def _error_line(event: ErrorEvent) -> str:
    # pragma: no mutate justification: transient is a wire-contract field
    # (the JSONL payload shows it); the engine only ever emits True today,
    # so the non-retry arm is unreachable.
    retry = " (will retry)" if event.transient else ""  # pragma: no mutate
    return f"error: {event.message}{retry}"


def _poll_text(stamp: str, event: PollEvent, out: HumanOutput) -> Text:
    """The per-tick census — plain row, severity-colored used-pct segment."""
    from rich.text import Text

    text = Text(stamp)
    if event.active is None:
        text.append("poll: no active account")
        return text
    active = event.active
    text.append(f"{active}: ")
    text.append(*_used_segment(event, active, out))
    others = ", ".join(
        f"{name}: {_poll_describe(event, name)}" for name in event.headroom if name != active
    )
    tail = f" | others: {others}" if others else ""
    text.append(f" (switch at {event.threshold:g}%){tail}")
    return text


def _used_segment(event: PollEvent, active: str, out: HumanOutput) -> tuple[str, str]:
    """The active account's ``N% used`` — ramp-colored, dim when unknown."""
    headroom = event.headroom.get(active)
    if headroom is not None:
        used_pct = 100.0 - headroom
        return f"{used_pct:.0f}% used", out.severity_style(used_pct)
    err = event.fetch_errors.get(active)
    cause = f"usage unknown ({err})" if err else "usage unknown"
    return cause, out.severity_style(None)


def _poll_describe(event: PollEvent, name: str) -> str:
    """One parked account in the census — its windows, or the cause.

    ``windows`` and ``headroom`` come from the same ``relevant_windows`` set,
    so headroom never exists without a window — the cause chain is the only
    fallback worth rendering.
    """
    windows = event.windows.get(name)
    if windows:
        return " · ".join(f"{label} {pct:.0f}%" for label, pct in windows.items())
    err = event.fetch_errors.get(name)
    return f"? ({err})" if err else "?"
