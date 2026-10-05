"""Fake ``DiagnosticsPort`` — canned facts, overridable per test."""

from collections.abc import Mapping
from pathlib import Path

from claude_acc_manager.accounts.application.doctor_report import (
    DiagnosticsFacts,
    LockObservation,
)
from claude_acc_manager.shared.claude_contract import ClaudeContract, contract_for_version

DEFAULT_ENV: dict[str, str] = {"TERM": "xterm-256color", "COLORTERM": "truecolor"}


def facts(
    *,
    contract: ClaudeContract | None = None,
    store_root: Path = Path("/store"),
    store_exists: bool = True,
    accounts_dir: Path = Path("/store/accounts"),
    accounts_dir_exists: bool = True,
    credentials_path: Path = Path("/home/.claude/.credentials.json"),
    credentials_present: bool = True,
    config_path: Path = Path("/home/.claude.json"),
    config_present: bool = True,
    locks: tuple[LockObservation, ...] = (),
    env: Mapping[str, str] | None = None,
    stdin_tty: bool = True,
    stdout_tty: bool = True,
    interactive: bool = True,
    euid: int = 1000,
    in_container: bool = False,
    python: str = "CPython 3.12.0",
    platform: str = "Linux-6.0-test",
) -> DiagnosticsFacts:
    """A coherent fact set; override the fields a test steers."""
    return DiagnosticsFacts(
        contract=contract or contract_for_version((2, 1, 288)),
        store_root=store_root,
        store_exists=store_exists,
        accounts_dir=accounts_dir,
        accounts_dir_exists=accounts_dir_exists,
        credentials_path=credentials_path,
        credentials_present=credentials_present,
        config_path=config_path,
        config_present=config_present,
        locks=locks,
        env=env if env is not None else DEFAULT_ENV,
        stdin_tty=stdin_tty,
        stdout_tty=stdout_tty,
        interactive=interactive,
        euid=euid,
        in_container=in_container,
        python=python,
        platform=platform,
    )


class FakeDiagnostics:
    """``DiagnosticsPort`` fake — returns one injected fact set."""

    def __init__(self, report_facts: DiagnosticsFacts | None = None) -> None:
        """Pin the facts ``probe`` returns (defaults to a healthy box)."""
        self._facts = report_facts or facts()

    def probe(self) -> DiagnosticsFacts:
        """Return the canned facts."""
        return self._facts
