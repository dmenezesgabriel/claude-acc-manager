"""argv → handler → exit code: parse, root-guard, dispatch, serialize once."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import TYPE_CHECKING

import claude_acc_manager
from claude_acc_manager.cli.context import ProcessContext, UseCases
from claude_acc_manager.cli.human import HumanOutput
from claude_acc_manager.cli.json_output import error_envelope
from claude_acc_manager.cli.parser import build_parser
from claude_acc_manager.shared.claude_contract import UnsupportedClaudeVersionError

if TYPE_CHECKING:
    from rich.console import Console


def _emit_error(error_type: str, message: str, args: argparse.Namespace, out: HumanOutput) -> int:
    """Route a handled failure: JSON envelope on stdout, else stderr text."""
    if args.json:
        print(json.dumps(error_envelope(error_type, message), indent=2))
        return 1
    out.error(f"error: {message}")
    return 1


def _failure_fields(exc: Exception) -> tuple[str, str]:
    """Map a use-case failure onto its envelope type token and message.

    ``UnsupportedClaudeVersionError`` must be checked before ``ValueError``
    (its base class) so --json consumers get the stable contract-refusal
    token, not the generic validation bucket.
    """
    if isinstance(exc, KeyError):
        return "KeyError", f"no such account: {exc}"
    if isinstance(exc, UnsupportedClaudeVersionError):
        return "UnsupportedClaudeVersion", str(exc)
    if isinstance(exc, TimeoutError):
        # A lock held past its bound — another cam operation or claude
        # itself is mid-write; retrying later is the remedy.
        return "TimeoutError", str(exc)
    return "ValueError", str(exc)


def _bare_interactive_argv(
    argv: Sequence[str] | None, process: ProcessContext
) -> Sequence[str] | None:
    """Swap a bare interactive invocation for ``["tui"]``; pass the rest through.

    A bare ``cam`` at a terminal is a person, not a script — the dashboard is
    the sensible default. Pipes and scripts (``interactive`` false) keep the
    no-command usage fallback in ``run``.
    """
    if not argv and process.interactive:
        return ["tui"]
    return argv


def run(
    argv: Sequence[str] | None,
    use_cases: UseCases,
    *,
    process: ProcessContext,
    console: Console | None = None,
) -> int:
    """Parse *argv*, dispatch to the matching command, return the exit code.

    Prints a friendly ``error: ...`` line for the failures the use cases raise
    (``ValueError`` for a bad login, ``KeyError`` for an unknown account).
    Refuses to dispatch as root outside a container (§8.6) — the check sits
    between parse and dispatch so ``--help`` still works. Bare ``cam`` opens
    the TUI on an interactive terminal and prints usage otherwise.
    """
    out = HumanOutput(console)
    parser = build_parser()
    args = parser.parse_args(_bare_interactive_argv(argv, process))
    if args.version:
        out.print(f"cam {claude_acc_manager.package_version()}")
        return 0
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_usage(sys.stderr)
        return 2
    if process.euid == 0 and not process.in_container:
        return _emit_error(
            "RootRefused", "refusing to run as root (outside a container)", args, out
        )
    try:
        result = handler(args, use_cases, out)
    except (KeyError, ValueError, TimeoutError) as exc:
        error_type, message = _failure_fields(exc)
        return _emit_error(error_type, message, args, out)
    except KeyboardInterrupt:
        # The stdout purity guarantee covers handled errors, not Ctrl-C —
        # the cancellation note goes to stderr in --json mode.
        if args.json:
            out.error("\noperation cancelled")
        else:
            out.print("\noperation cancelled")
        return 130
    if isinstance(result, dict):
        print(json.dumps(result, indent=2))
        return 0
    return result
