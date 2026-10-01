"""The ``cam`` command's argparse dispatch — transport only, no wiring.

M3 scope: ``add`` / ``remove`` / ``list`` / ``status`` with plain-text output;
the full command set, ``--json`` and the root guard land in M7 (docs/backlog.md). This
module reaches the components only through use cases (ADR-0010); the
concrete adapters are wired in ``__main__`` and passed in as :class:`UseCases`,
so tests drive :func:`run` with in-memory fakes.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from claude_acc_manager.accounts.application.ports import AccountDirPort, AccountStorePort
from claude_acc_manager.accounts.application.use_cases.add_account import AddAccount
from claude_acc_manager.accounts.application.use_cases.list_accounts import ListAccounts
from claude_acc_manager.accounts.application.use_cases.quarantine_account import (
    QuarantineAccount,
)
from claude_acc_manager.accounts.application.use_cases.remove_account import RemoveAccount
from claude_acc_manager.accounts.application.use_cases.status_account import StatusAccount
from claude_acc_manager.accounts.application.use_cases.switch_account import (
    SwitchAccount,
    SwitchResult,
)
from claude_acc_manager.accounts.domain.credential_fields import refresh_token_fingerprint
from claude_acc_manager.accounts.domain.services.switch_selection import SwitchStrategy
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.usage.application.ports import UsageCachePort
from claude_acc_manager.usage.application.use_cases.fetch_account_usage import (
    FetchAccountUsage,
    UsageReport,
)
from claude_acc_manager.usage.domain.services.headroom import account_headroom


@dataclass(frozen=True)
class UseCases:
    """The account and usage use cases the CLI dispatches to."""

    add: AddAccount
    remove: RemoveAccount
    list_accounts: ListAccounts
    status: StatusAccount
    fetch_usage: FetchAccountUsage
    switch: SwitchAccount
    quarantine: QuarantineAccount
    account_store: AccountStorePort
    account_files: AccountDirPort
    usage_cache: UsageCachePort


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
    # ADR-0009: the live config's accountUuid — not the registry pointer —
    # decides which account owns the live slot; the pointer can drift.
    status = use_cases.status.execute()
    is_active = status is not None and status.managed_as == name.value
    report = use_cases.fetch_usage.execute(name.value, is_active=is_active)
    _print_usage_report(report)
    if report.permanent_auth_error:
        _quarantine_dead_lineage(name, use_cases)
    return 0


def _quarantine_dead_lineage(name: AccountName, use_cases: UseCases) -> None:
    """Tombstone the parked lineage the provider permanently rejected."""
    parked = use_cases.account_files.read_credentials(use_cases.account_store.account_dir(name))
    fingerprint = refresh_token_fingerprint(parked) if parked is not None else None
    use_cases.quarantine.execute(name, "permanent_auth_error", fingerprint)
    print(f"quarantined {name.value!r}: the provider permanently rejected its refresh token")


def _cached_headroom(use_cases: UseCases) -> dict[str, float | None]:
    """Per-account headroom from the usage cache (``None`` = unmeasured)."""
    return {
        account.name.value: account_headroom(
            use_cases.usage_cache.load(account.name.value).last_good
        )
        for account in use_cases.account_store.list_accounts()
    }


def _cmd_switch(args: argparse.Namespace, use_cases: UseCases) -> int:
    target = AccountName(args.name) if args.name else None
    if target is not None and use_cases.account_store.get(target) is None:
        raise KeyError(target.value)
    headroom = _cached_headroom(use_cases) if args.strategy else None
    # cast() is a runtime no-op — argparse's choices= already proved the
    # literal; mutants of the type argument are equivalent by construction.
    strategy = cast("SwitchStrategy", args.strategy) if args.strategy else None  # pragma: no mutate
    # args.model is accepted for flag parity but not persisted — settings
    # storage (autoswitch.model) lands with M9.
    result = use_cases.switch.execute(
        target, strategy=strategy, headroom=headroom, dry_run=args.dry_run
    )
    _print_switch_result(result)
    return 0


_STAY_MESSAGES: dict[str, str] = {
    "no-valid-target": "no valid switch target",
    "candidates-exhausted": "every candidate is at its limit",
    "usage-unavailable": "usage unknown — cannot rank candidates",
    "already-best": "the active account already has the most headroom",
}


def _print_switch_result(result: SwitchResult) -> None:
    """Render the switch outcome; the printed wording is the interface."""
    prefix = "dry run: " if result.dry_run else ""
    if result.outcome == "switched":
        _print_switched(result, prefix)
    elif result.outcome == "already-active":
        print(f"{prefix}{result.target!r} is already the active account")
    else:
        print(f"{prefix}{_STAY_MESSAGES[result.outcome]}")
    for candidate in result.skipped:
        print(f"{prefix}skipped {candidate.name!r}: {candidate.reason}")


def _print_switched(result: SwitchResult, prefix: str) -> None:
    """The success line plus its side-effect notes."""
    if result.previous is not None:
        was = repr(result.previous)
    elif result.unmanaged_live:
        was = "an unmanaged login"
    else:
        was = "no login"
    print(f"{prefix}switched to {result.target!r} (was {was})")
    if result.unmanaged_live:
        where = result.preserved_to if result.preserved_to else "unclaimed/"
        print(f"{prefix}the previous unmanaged login was preserved under {where}")
    for name in result.quarantined:
        print(f"{prefix}quarantined the wiped credential of {name!r}")


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

    switch = subparsers.add_parser("switch", help="move the live claude login to another account")
    switch.add_argument("name", nargs="?", help="account name (omit to rotate)")
    switch.add_argument(
        "--strategy",
        choices=["best", "next-available"],
        help="pick a target from cached usage instead of naming one",
    )
    switch.add_argument(
        "--dry-run",
        action="store_true",
        help="describe the switch without applying it",
    )
    switch.add_argument(
        "--model",
        help="model preference for cam auto — accepted but not persisted yet",
    )
    switch.set_defaults(handler=_cmd_switch)
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
