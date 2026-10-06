"""The ``cam doctor`` report and the raw facts it is assembled from.

``DiagnosticsFacts`` is what a ``DiagnosticsPort`` probe returns — raw OS
observations with no verdicts. ``CollectDoctorReport`` turns them into a
``DoctorReport``: sections of ``DoctorCheck`` rows where ``status`` carries
the verdict the renderer colors (``ok``/``warn``/``fail`` — ``info`` rows
are plain facts). Plain frozen dataclasses keep a ``--json`` flag additive.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from claude_acc_manager.shared.claude_contract import ClaudeContract

DoctorStatus = Literal["ok", "warn", "fail", "info"]
"""Verdict badge on a report row: colored check, or ``info`` for a fact."""

LockState = Literal["free", "held", "stale"]
"""A mkdir lock's liveness: absent, fresh enough to have a live holder, or
old enough that its holder is presumed dead."""


@dataclass(frozen=True)
class LockObservation:
    """One coordination lock's state at probe time.

    ``age_s`` is the lock dir's age when it exists (the holder's heartbeat);
    ``None`` when free.
    """

    name: str
    path: Path
    state: LockState
    age_s: float | None


@dataclass(frozen=True)
class DiagnosticsFacts:
    """Everything the doctor report shows, taken at one instant.

    Raw observations only — ``env`` arrives whole so the use case picks the
    variables worth showing; the probe stays free of report policy.
    """

    contract: ClaudeContract
    store_root: Path
    store_exists: bool
    accounts_dir: Path
    accounts_dir_exists: bool
    credentials_path: Path
    credentials_present: bool
    config_path: Path
    config_present: bool
    locks: tuple[LockObservation, ...]
    env: Mapping[str, str]
    stdin_tty: bool
    stdout_tty: bool
    interactive: bool
    euid: int
    in_container: bool
    python: str
    platform: str


@dataclass(frozen=True)
class DoctorCheck:
    """One report row: a label, its value, and the verdict to color.

    ``info`` rows are pure facts (paths, env values); ``ok``/``warn``/``fail``
    carry a badge the renderer styles green/yellow/red.
    """

    name: str
    value: str
    status: DoctorStatus


@dataclass(frozen=True)
class DoctorSection:
    """A titled group of checks (``cam``, ``claude contract``, ...)."""

    title: str
    checks: tuple[DoctorCheck, ...]


@dataclass(frozen=True)
class DoctorReport:
    """The whole diagnostics report, rendered section by section."""

    sections: tuple[DoctorSection, ...]
