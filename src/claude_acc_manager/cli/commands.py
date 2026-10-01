"""The ``_cmd_*`` handlers — orchestrate a use case, render the outcome.

Each handler returns ``int`` for the exit code, or the schema-v1 dict under
``--json`` (``dispatch.run`` owns the one ``json.dumps``). Human wording is
the interface; the pinned strings live in ``test/unit/test_cli.py``.
"""

import argparse
from typing import cast

from claude_acc_manager.accounts.application.use_cases.switch_account import SwitchResult
from claude_acc_manager.accounts.domain.services.switch_selection import SwitchStrategy
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.cli.context import UseCases
from claude_acc_manager.cli.json_output import (
    list_payload,
    status_payload,
    switch_message,
    switch_payload,
    usage_payload,
)
from claude_acc_manager.usage.application.use_cases.fetch_account_usage import UsageReport
from claude_acc_manager.usage.domain.services.headroom import account_headroom


def cmd_add(args: argparse.Namespace, use_cases: UseCases) -> int:
    """Register the account via an isolated login; print the confirmation."""
    use_cases.add.execute(AccountName(args.name))
    print(f"added account {args.name!r}")
    return 0


def cmd_remove(args: argparse.Namespace, use_cases: UseCases) -> int:
    """Unregister the account and its login dir; print the confirmation."""
    use_cases.remove.execute(AccountName(args.name))
    print(f"removed account {args.name!r}")
    return 0


def cmd_list(args: argparse.Namespace, use_cases: UseCases) -> int | dict[str, object]:
    """List registered accounts — marked rows, or the schema-v1 payload."""
    summaries = use_cases.list_accounts.execute()
    if args.json:
        return list_payload(summaries, use_cases)
    if not summaries:
        print("no accounts registered")
        return 0
    for summary in summaries:
        marker = "*" if summary.is_active else " "
        row = f"{marker} {summary.account.name.value}\t{summary.account.email}"
        if not summary.account.enabled:
            row += " [disabled]"
        if summary.is_quarantined:
            row += " [quarantined]"
        print(row)
    return 0


def cmd_status(args: argparse.Namespace, use_cases: UseCases) -> int | dict[str, object]:
    """Show the live login — one line, or the schema-v1 payload."""
    status = use_cases.status.execute()
    if args.json:
        return status_payload(status, use_cases)
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


def cmd_usage(args: argparse.Namespace, use_cases: UseCases) -> int | dict[str, object]:
    """Show one account's quota — text, or the schema-v1 payload."""
    name = AccountName(args.name)
    if use_cases.account_store.get(name) is None:
        raise KeyError(name.value)
    # ADR-0009: the live config's accountUuid — not the registry pointer —
    # decides which account owns the live slot; the pointer can drift.
    status = use_cases.status.execute()
    is_active = status is not None and status.managed_as == name.value
    report = use_cases.fetch_usage.execute(name.value, is_active=is_active)
    quarantined = False
    if report.permanent_auth_error:
        use_cases.quarantine_dead_lineage.execute(name)
        quarantined = True
    if args.json:
        return usage_payload(name.value, report, quarantined)
    _print_usage_report(report)
    if quarantined:
        print(f"quarantined {name.value!r}: the provider permanently rejected its refresh token")
    return 0


def _cached_headroom(use_cases: UseCases) -> dict[str, float | None]:
    """Per-account headroom from the usage cache (``None`` = unmeasured)."""
    return {
        account.name.value: account_headroom(
            use_cases.usage_cache.load(account.name.value).last_good
        )
        for account in use_cases.account_store.list_accounts()
    }


def cmd_switch(args: argparse.Namespace, use_cases: UseCases) -> int | dict[str, object]:
    """Switch the live login — text render, or the schema-v1 payload."""
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
    if args.json:
        return switch_payload(result, args.strategy, use_cases)
    _print_switch_result(result)
    return 0


def _print_switch_result(result: SwitchResult) -> None:
    """Render the switch outcome; the printed wording is the interface."""
    prefix = "dry run: " if result.dry_run else ""
    print(switch_message(result))
    if result.outcome == "switched":
        _print_switch_notes(result, prefix)
    for candidate in result.skipped:
        print(f"{prefix}skipped {candidate.name!r}: {candidate.reason}")


def _print_switch_notes(result: SwitchResult, prefix: str) -> None:
    """The preservation/quarantine notes that follow a real switch line."""
    if result.unmanaged_live:
        where = result.preserved_to if result.preserved_to else "unclaimed/"
        print(f"{prefix}the previous unmanaged login was preserved under {where}")
    for name in result.quarantined:
        print(f"{prefix}quarantined the wiped credential of {name!r}")


def cmd_disable(args: argparse.Namespace, use_cases: UseCases) -> int:
    """Hold the account out of automatic switching."""
    return _set_enabled(args, use_cases, enabled=False)


def cmd_enable(args: argparse.Namespace, use_cases: UseCases) -> int:
    """Return a disabled account to automatic switching."""
    return _set_enabled(args, use_cases, enabled=True)


def _set_enabled(args: argparse.Namespace, use_cases: UseCases, enabled: bool) -> int:
    """Toggle the account and print the confirmation plus safety notes."""
    name = AccountName(args.name)
    account = use_cases.account_store.get(name)
    if account is None:
        raise KeyError(name.value)
    verb = "enabled" if enabled else "disabled"
    if account.enabled == enabled:
        print(f"account {name.value!r} is already {verb}")
        return 0
    use_cases.set_enabled.execute(name, enabled)
    print(f"{verb} account {name.value!r}")
    if enabled:
        print("  it is back in the rotation")
        return 0
    _print_disable_notes(name.value, use_cases)
    return 0


def _print_disable_notes(name: str, use_cases: UseCases) -> None:
    """The footgun warnings that follow a disable (claude-swap port)."""
    active = use_cases.account_store.active()
    if active is not None and active.name.value == name:
        print(
            f"  note: {name!r} is the active account — it stays live until you "
            "switch away; it just won't be an automatic switch target"
        )
    if not any(account.enabled for account in use_cases.account_store.list_accounts()):
        print(
            "  warning: no enabled accounts remain in rotation — automatic "
            "switching has nothing to pick (re-enable one with cam enable <name>)"
        )
