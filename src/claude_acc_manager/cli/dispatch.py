"""argv → handler → exit code: parse, root-guard, dispatch, serialize once."""

import argparse
import json
import sys
from collections.abc import Sequence

from claude_acc_manager.cli.context import ProcessContext, UseCases
from claude_acc_manager.cli.json_output import error_envelope
from claude_acc_manager.cli.parser import build_parser


def _emit_error(error_type: str, message: str, args: argparse.Namespace) -> int:
    """Route a handled failure: JSON envelope on stdout, else stderr text."""
    if args.json:
        print(json.dumps(error_envelope(error_type, message), indent=2))
        return 1
    print(f"error: {message}", file=sys.stderr)
    return 1


def run(argv: Sequence[str] | None, use_cases: UseCases, *, process: ProcessContext) -> int:
    """Parse *argv*, dispatch to the matching command, return the exit code.

    Prints a friendly ``error: ...`` line for the failures the use cases raise
    (``ValueError`` for a bad login, ``KeyError`` for an unknown account).
    Refuses to dispatch as root outside a container (§8.6) — the check sits
    between parse and dispatch so ``--help`` still works and bare ``cam``
    still prints usage (claude-swap cli.py _guard_root's placement).
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_usage(sys.stderr)
        return 2
    if process.euid == 0 and not process.in_container:
        return _emit_error("RootRefused", "refusing to run as root (outside a container)", args)
    try:
        result = handler(args, use_cases)
    except KeyError as exc:
        return _emit_error("KeyError", f"no such account: {exc}", args)
    except ValueError as exc:
        return _emit_error("ValueError", str(exc), args)
    except KeyboardInterrupt:
        # The stdout purity guarantee covers handled errors, not Ctrl-C —
        # the cancellation note goes to stderr in --json mode (claude-swap's rule).
        print(
            "\noperation cancelled",
            file=sys.stderr if args.json else sys.stdout,
        )
        return 130
    if isinstance(result, dict):
        print(json.dumps(result, indent=2))
        return 0
    return result
