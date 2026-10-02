"""auto_event — the typed events one engine tick emits, plus its outcome.

Pure data: the engine emits these to an injected sink and transports
(CLI human text / JSONL, later the TUI) render them. Nothing here reads a
clock or knows JSON — the renderer stamps timestamps if it wants them.

Kinds mirror the reference engine's, minus the deferred axes (failover,
consume-first, model config warnings): ``poll`` (the per-tick census),
``switch``, ``no-switch`` (with a machine-readable ``reason``),
``account-quarantined``, ``all-exhausted``, and ``error``. ``sleep`` is
emitted by the loop driver, not the tick.

Example:
    engine = AutoEngine(..., emit=events.append)
    outcome = engine.tick()  # events holds PollEvent + one terminal event
"""

import enum
from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class AutoEvent:
    """Base event. ``kind`` is the JSONL wire discriminator."""

    kind: ClassVar[str] = "event"


@dataclass(frozen=True)
class PollEvent(AutoEvent):
    """The per-tick census: who is active, each account's headroom, why unknown.

    ``windows`` carries the per-window percentages so a bare "89%" doesn't
    hide which window binds (claude-swap #115). ``fetch_errors`` names the
    last fetch cause for accounts whose usage stayed unknown this tick.
    """

    kind: ClassVar[str] = "poll"
    active: str | None
    headroom: dict[str, float | None]
    threshold: float
    fetch_errors: dict[str, str]
    windows: dict[str, dict[str, float]]


@dataclass(frozen=True)
class SwitchEvent(AutoEvent):
    """A real (or dry-run) move: trigger, source, target."""

    kind: ClassVar[str] = "switch"
    trigger: str
    from_name: str | None
    to_name: str | None
    dry_run: bool = False


@dataclass(frozen=True)
class NoSwitchEvent(AutoEvent):
    """The tick decided not to move; ``reason`` is machine-readable."""

    kind: ClassVar[str] = "no-switch"
    reason: str
    detail: str = ""


@dataclass(frozen=True)
class QuarantinedEvent(AutoEvent):
    """A freshen provably killed the lineage — tombstone recorded."""

    kind: ClassVar[str] = "account-quarantined"
    name: str
    reason: str


@dataclass(frozen=True)
class AllExhaustedEvent(AutoEvent):
    """Every candidate measured and at its limit — nothing to switch to.

    ``earliest_reset_at_s`` is the fleet's earliest provable recovery epoch
    (the loop sleeps until then); ``None`` when no account reports one.
    """

    kind: ClassVar[str] = "all-exhausted"
    earliest_reset_at_s: float | None


@dataclass(frozen=True)
class ErrorEvent(AutoEvent):
    """A tick-level failure. ``transient`` means worth retrying next tick."""

    kind: ClassVar[str] = "error"
    message: str
    transient: bool = True


class TickOutcome(enum.IntEnum):
    """Outcome of one evaluation tick; values double as --once exit codes."""

    SWITCHED = 0
    ERROR = 1
    NO_ACTION = 2
    BLOCKED = 3  # wanted to switch but no viable target / all exhausted
