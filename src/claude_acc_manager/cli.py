"""The ``cam`` command's argparse dispatch — transport only, no wiring.

M3 scope: ``add`` / ``remove`` / ``list`` / ``status`` with plain-text output;
the full command set, ``--json`` and the root guard land in M7 (plan §9). This
module reaches the components only through use cases (plan §4.1 rule 8); the
concrete adapters are wired in ``__main__`` and passed in as :class:`UseCases`,
so tests drive :func:`run` with in-memory fakes.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from claude_acc_manager.accounts.application.ports import AccountStorePort
from claude_acc_manager.accounts.application.use_cases.add_account import AddAccount
from claude_acc_manager.accounts.application.use_cases.list_accounts import ListAccounts
from claude_acc_manager.accounts.application.use_cases.remove_account import RemoveAccount
from claude_acc_manager.accounts.application.use_cases.status_account import StatusAccount
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.usage.application.use_cases.fetch_account_usage import (
    FetchAccountUsage,
    UsageReport,
)


@dataclass(frozen=True)
class UseCases:
    """The account and usage use cases the CLI dispatches to."""

    add: AddAccount
    remove: RemoveAccount
    list_accounts: ListAccounts
    status: StatusAccount
    fetch_usage: FetchAccountUsage
    account_store: AccountStorePort


def _cmd_add(args: argparse.Namespace, use_cases: UseCases) -> int:
    use_cases.add.execute(AccountName(args.name))
    print(f"added account {args.name!r}")
    return 0


def _cmd_remove(args: argparse.Namespace, use_cases: UseCases) -> int:
    use_cases.remove.execute(AccountName(args.name))
    print(f"removed account {args.name!r}")
    return 0


def _cmd_list(_args: argparse.Namespace, use_cases: UseCases) -> int:
    summaries = use_cases.list_accounts.execute()
    if not summaries:
        print("no accounts registered")
        return 0
    for summary in summaries:
        marker = "*" if summary.is_active else " "
        print(f"{marker} {summary.account.name.value}\t{summary.account.email}")
    return 0


def _cmd_status(_args: argparse.Namespace, use_cases: UseCases) -> int:
    status = use_cases.status.execute()
    if status is None:
        print("no account is logged in")
        return 0
    where = f"managed as {status.managed_as!r}" if status.managed_as else "not managed"
    print(f"logged in as {status.email} ({where})")
    return 0


def _print_usage_report(report: UsageReport) -> None:
    if report.snapshot is None:
        print(f"usage unknown: {report.last_error}")
        return
    if report.snapshot.five_hour is not None:
        print(f"five_hour: {report.snapshot.five_hour.pct:.0f}%")
    if report.snapshot.seven_day is not None:
        print(f"seven_day: {report.snapshot.seven_day.pct:.0f}%")
    for scoped in report.snapshot.scoped:
        print(f"{scoped.name}: {scoped.pct:.0f}%")
    if report.stale:
        print(f"(stale: {report.last_error})")


def _cmd_usage(args: argparse.Namespace, use_cases: UseCases) -> int:
    name = AccountName(args.name)
    if use_cases.account_store.get(name) is None:
        raise KeyError(name.value)
    active = use_cases.account_store.active()
    is_active = active is not None and active.name == name
    _print_usage_report(use_cases.fetch_usage.execute(name.value, is_active=is_active))
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the ``cam`` argument parser (each subcommand sets a ``handler``)."""
    parser = argparse.ArgumentParser(prog="cam", description="manage Claude Code OAuth accounts")
    subparsers = parser.add_subparsers()

    add = subparsers.add_parser("add", help="register an account via an isolated claude login")
    add.add_argument("name", help="account name")
    add.set_defaults(handler=_cmd_add)

    remove = subparsers.add_parser("remove", help="unregister an account and delete its login dir")
    remove.add_argument("name", help="account name")
    remove.set_defaults(handler=_cmd_remove)

    subparsers.add_parser("list", help="list registered accounts").set_defaults(handler=_cmd_list)
    subparsers.add_parser("status", help="show the account the live claude slot uses").set_defaults(
        handler=_cmd_status
    )

    usage = subparsers.add_parser("usage", help="show one account's quota usage")
    usage.add_argument("name", help="account name")
    usage.set_defaults(handler=_cmd_usage)
    return parser


def run(argv: Sequence[str] | None, use_cases: UseCases) -> int:
    """Parse *argv*, dispatch to the matching command, return the exit code.

    Prints a friendly ``error: ...`` line for the failures the use cases raise
    (``ValueError`` for a bad login, ``KeyError`` for an unknown account).
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_usage(sys.stderr)
        return 2
    try:
        return handler(args, use_cases)
    except KeyError as exc:
        print(f"error: no such account: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
