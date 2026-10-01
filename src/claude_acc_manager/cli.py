"""The ``cam`` command's argparse dispatch — transport only, no wiring.

Subcommands print plain text for humans; payload-bearing verbs also take
``--json`` and emit the schema-v1 contract (docs/slices SL-007): one
``json.dumps`` object on stdout, camelCase keys, handled failures as an
error envelope on stdout. This module reaches the components only through
use cases (ADR-0010); the concrete adapters are wired in ``__main__`` and
passed in as :class:`UseCases`, so tests drive :func:`run` with in-memory
fakes.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NamedTuple, cast

from claude_acc_manager.accounts.application.ports import AccountDirPort, AccountStorePort
from claude_acc_manager.accounts.application.use_cases.add_account import AddAccount
from claude_acc_manager.accounts.application.use_cases.list_accounts import (
    AccountSummary,
    ListAccounts,
)
from claude_acc_manager.accounts.application.use_cases.quarantine_account import (
    QuarantineAccount,
)
from claude_acc_manager.accounts.application.use_cases.remove_account import RemoveAccount
from claude_acc_manager.accounts.application.use_cases.set_account_enabled import (
    SetAccountEnabled,
)
from claude_acc_manager.accounts.application.use_cases.status_account import (
    ActiveAccountStatus,
    StatusAccount,
)
from claude_acc_manager.accounts.application.use_cases.switch_account import (
    SwitchAccount,
    SwitchResult,
)
from claude_acc_manager.accounts.domain.credential_fields import refresh_token_fingerprint
from claude_acc_manager.accounts.domain.services.switch_selection import SwitchStrategy
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.usage.application.ports import ClockPort, UsageCachePort
from claude_acc_manager.usage.application.use_cases.fetch_account_usage import (
    FetchAccountUsage,
    UsageReport,
)
from claude_acc_manager.usage.domain.services import cache_trust, poll_policy
from claude_acc_manager.usage.domain.services.headroom import account_headroom
from claude_acc_manager.usage.domain.usage_cache_entry import UsageCacheEntry
from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot

SCHEMA_VERSION = 1


class ProcessContext(NamedTuple):
    """What the transport knows about the invoking process.

    ``euid`` feeds the root guard (docs/architecture.md §8.6): uid 0 is
    refused unless ``in_container``, where root is routine. Both fields are
    probed by the composition root — ``__main__`` reads ``os.geteuid()`` and
    ``shared.container.running_in_container``.
    """

    euid: int
    in_container: bool


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
    set_enabled: SetAccountEnabled
    account_store: AccountStorePort
    account_files: AccountDirPort
    usage_cache: UsageCachePort
    usage_clock: ClockPort


def _cmd_add(args: argparse.Namespace, use_cases: UseCases) -> int:
    use_cases.add.execute(AccountName(args.name))
    print(f"added account {args.name!r}")
    return 0


def _cmd_remove(args: argparse.Namespace, use_cases: UseCases) -> int:
    use_cases.remove.execute(AccountName(args.name))
    print(f"removed account {args.name!r}")
    return 0


def _cmd_list(args: argparse.Namespace, use_cases: UseCases) -> int | dict[str, object]:
    summaries = use_cases.list_accounts.execute()
    if args.json:
        return _list_payload(summaries, use_cases)
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


def _cmd_status(args: argparse.Namespace, use_cases: UseCases) -> int | dict[str, object]:
    status = use_cases.status.execute()
    if args.json:
        return _status_payload(status, use_cases)
    if status is None:
        print("no account is logged in")
        return 0
    where = f"managed as {status.managed_as!r}" if status.managed_as else "not managed"
    print(f"logged in as {status.email} ({where})")
    return 0


def _status_payload(status: ActiveAccountStatus | None, use_cases: UseCases) -> dict[str, object]:
    """The ``status --json`` payload — null, unmanaged, or managed live login."""
    if status is None:
        return {"schemaVersion": SCHEMA_VERSION, "active": None}
    if status.managed_as is None:
        active = _live_identity(status)
        active["managed"] = False
        return {"schemaVersion": SCHEMA_VERSION, "active": active}
    quarantined = status.managed_as in {
        tombstone.name for tombstone in use_cases.account_store.quarantined()
    }
    active = _live_identity(status)
    active["isOrganization"] = bool(status.organization_uuid)
    active["managed"] = True
    active["managedAs"] = status.managed_as
    entry = use_cases.usage_cache.load(status.managed_as)
    active.update(_usage_row_fields(entry, quarantined, use_cases.usage_clock.now_epoch_s()))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "active": active,
        "totalManagedAccounts": len(use_cases.account_store.list_accounts()),
    }


def _live_identity(status: ActiveAccountStatus) -> dict[str, object]:
    """The live login's identity fields, shared by both ``active`` shapes."""
    return {
        "email": status.email,
        "accountUuid": status.account_uuid,
        "organizationUuid": status.organization_uuid,
        "organizationName": status.organization_name,
    }


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


def _window_json(pct: float, resets_at: str | None) -> dict[str, object]:
    """Project one window; ``resetsAt`` is absent when the provider omits it."""
    payload: dict[str, object] = {"pct": pct}
    if resets_at is not None:
        payload["resetsAt"] = resets_at
    return payload


def _snapshot_json(snapshot: UsageSnapshot) -> dict[str, object]:
    """Project the snapshot into the schema-v1 ``usage`` object."""
    payload: dict[str, object] = {}
    if snapshot.five_hour is not None:
        payload["fiveHour"] = _window_json(snapshot.five_hour.pct, snapshot.five_hour.resets_at)
    if snapshot.seven_day is not None:
        payload["sevenDay"] = _window_json(snapshot.seven_day.pct, snapshot.seven_day.resets_at)
    payload["scoped"] = [
        {"name": window.name, **_window_json(window.pct, window.resets_at)}
        for window in snapshot.scoped
    ]
    return payload


def _usage_payload(account: str, report: UsageReport, quarantined: bool) -> dict[str, object]:
    """The schema-v1 ``usage --json`` payload; *quarantined* means this run."""
    return {
        "schemaVersion": SCHEMA_VERSION,
        "account": account,
        "usageStatus": "ok" if report.snapshot is not None else "unavailable",
        "usage": _snapshot_json(report.snapshot) if report.snapshot is not None else None,
        "stale": report.stale,
        "usageError": report.last_error,
        "permanentAuthError": report.permanent_auth_error,
        "quarantined": quarantined,
    }


def _timestamp(epoch_s: float) -> str:
    """ISO-8601 UTC seconds stamp for an epoch reading (``usageFetchedAt``)."""
    return (
        datetime.fromtimestamp(epoch_s, tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def _list_payload(summaries: list[AccountSummary], use_cases: UseCases) -> dict[str, object]:
    """The ``list --json`` payload — registry rows plus cached usage."""
    now_s = use_cases.usage_clock.now_epoch_s()
    return {
        "schemaVersion": SCHEMA_VERSION,
        "active": next(
            (summary.account.name.value for summary in summaries if summary.is_active),
            None,
        ),
        "accounts": [
            _account_row(summary, use_cases.usage_cache.load(summary.account.name.value), now_s)
            for summary in summaries
        ],
    }


def _account_row(
    summary: AccountSummary, entry: UsageCacheEntry, now_s: float
) -> dict[str, object]:
    """One list row: registry fields plus the cached-usage projection."""
    account = summary.account
    row: dict[str, object] = {
        "name": account.name.value,
        "email": account.email,
        "accountUuid": account.account_uuid,
        "organizationUuid": account.organization_uuid,
        "organizationName": account.organization_name,
        "isOrganization": bool(account.organization_uuid),
        "active": summary.is_active,
        "enabled": account.enabled,
        "quarantined": summary.is_quarantined,
    }
    row.update(_usage_row_fields(entry, summary.is_quarantined, now_s))
    return row


def _usage_row_fields(entry: UsageCacheEntry, quarantined: bool, now_s: float) -> dict[str, object]:
    """The ``usageStatus``/``usage``/failure fields for one list row.

    ``ok`` only while the cached measurement is decision-grade
    (cache_trust.trust_ok); a quarantined lineage reads
    ``relogin_required``; anything else — a stale row, a never-fetched
    account — is ``unavailable``. Display-grade ``lastGood*`` fields ride
    along whenever ``usage`` is null.
    """
    if quarantined:
        status = "relogin_required"
    elif cache_trust.trust_ok(
        entry,
        now_s,
        poll_policy.earliest_reset_epoch(entry.last_good),
        poll_policy.TRUST_MAX_AGE_S,
    ):
        status = "ok"
    else:
        status = "unavailable"
    fields: dict[str, object] = {"usageStatus": status, "usage": None}
    if status == "ok" and entry.last_good is not None and entry.fetched_at_s is not None:
        fields["usage"] = _snapshot_json(entry.last_good)
        fields["usageFetchedAt"] = _timestamp(entry.fetched_at_s)
        fields["usageAgeSeconds"] = round(now_s - entry.fetched_at_s, 1)
        return fields
    fields.update(_last_good_fields(entry, now_s))
    if status == "unavailable" and entry.last_error:
        fields["usageError"] = entry.last_error
        if entry.backoff_until_s is not None and cache_trust.in_backoff(entry, now_s):
            fields["usageRetryAt"] = _timestamp(entry.backoff_until_s)
    return fields


def _last_good_fields(entry: UsageCacheEntry, now_s: float) -> dict[str, object]:
    """Display-grade last-good usage for a row serving no trusted usage."""
    if entry.last_good is None or entry.fetched_at_s is None:
        return {}
    return {
        "lastGoodUsage": _snapshot_json(entry.last_good),
        "lastGoodFetchedAt": _timestamp(entry.fetched_at_s),
        "lastGoodAgeSeconds": round(now_s - entry.fetched_at_s, 1),
    }


def _cmd_usage(args: argparse.Namespace, use_cases: UseCases) -> int | dict[str, object]:
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
        _quarantine_dead_lineage(name, use_cases)
        quarantined = True
    if args.json:
        return _usage_payload(name.value, report, quarantined)
    _print_usage_report(report)
    if quarantined:
        print(f"quarantined {name.value!r}: the provider permanently rejected its refresh token")
    return 0


def _quarantine_dead_lineage(name: AccountName, use_cases: UseCases) -> None:
    """Tombstone the parked lineage the provider permanently rejected."""
    parked = use_cases.account_files.read_credentials(use_cases.account_store.account_dir(name))
    fingerprint = refresh_token_fingerprint(parked) if parked is not None else None
    use_cases.quarantine.execute(name, "permanent_auth_error", fingerprint)


def _cached_headroom(use_cases: UseCases) -> dict[str, float | None]:
    """Per-account headroom from the usage cache (``None`` = unmeasured)."""
    return {
        account.name.value: account_headroom(
            use_cases.usage_cache.load(account.name.value).last_good
        )
        for account in use_cases.account_store.list_accounts()
    }


def _cmd_switch(args: argparse.Namespace, use_cases: UseCases) -> int | dict[str, object]:
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
        return _switch_payload(result, args, use_cases)
    _print_switch_result(result)
    return 0


_STAY_MESSAGES: dict[str, str] = {
    "no-valid-target": "no valid switch target",
    "candidates-exhausted": "every candidate is at its limit",
    "usage-unavailable": "usage unknown — cannot rank candidates",
    "already-best": "the active account already has the most headroom",
}


def _switch_payload(
    result: SwitchResult, args: argparse.Namespace, use_cases: UseCases
) -> dict[str, object]:
    """The schema-v1 ``switch --json`` projection of a ``SwitchResult``."""
    emails = {a.name.value: a.email for a in use_cases.account_store.list_accounts()}
    return {
        "schemaVersion": SCHEMA_VERSION,
        "dryRun": result.dry_run,
        "switched": result.outcome == "switched",
        "outcome": result.outcome,
        "from": _account_ref(result.previous, emails),
        "to": _account_ref(result.target, emails),
        "unmanagedLive": result.unmanaged_live,
        "preservedTo": str(result.preserved_to) if result.preserved_to else None,
        "strategy": args.strategy,
        "skipped": [{"name": c.name, "reason": c.reason} for c in result.skipped],
        "quarantined": list(result.quarantined),
        "message": _switch_message(result),
    }


def _account_ref(name: str | None, emails: dict[str, str]) -> dict[str, object] | None:
    """A switch endpoint as ``{name, email}`` — ``None`` for no account."""
    if name is None:
        return None
    return {"name": name, "email": emails[name]}


def _switch_message(result: SwitchResult) -> str:
    """The first line of the human render — also the JSON ``message``."""
    prefix = "dry run: " if result.dry_run else ""
    if result.outcome == "switched":
        return f"{prefix}switched to {result.target!r} (was {_switch_from(result)})"
    if result.outcome == "already-active":
        return f"{prefix}{result.target!r} is already the active account"
    return f"{prefix}{_STAY_MESSAGES[result.outcome]}"


def _switch_from(result: SwitchResult) -> str:
    """The outgoing side of a switch line: a name, an unmanaged login, or none."""
    if result.previous is not None:
        return repr(result.previous)
    if result.unmanaged_live:
        return "an unmanaged login"
    return "no login"


def _print_switch_result(result: SwitchResult) -> None:
    """Render the switch outcome; the printed wording is the interface."""
    prefix = "dry run: " if result.dry_run else ""
    print(_switch_message(result))
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


def _cmd_disable(args: argparse.Namespace, use_cases: UseCases) -> int:
    return _set_enabled(args, use_cases, enabled=False)


def _cmd_enable(args: argparse.Namespace, use_cases: UseCases) -> int:
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


def build_parser() -> argparse.ArgumentParser:
    """Build the ``cam`` argument parser (each subcommand sets a ``handler``)."""
    parser = argparse.ArgumentParser(prog="cam", description="manage Claude Code OAuth accounts")
    parser.set_defaults(json=False)  # pragma: no mutate — jsonless commands still read args.json
    subparsers = parser.add_subparsers()

    add = subparsers.add_parser("add", help="register an account via an isolated claude login")
    add.add_argument("name", help="account name")
    add.set_defaults(handler=_cmd_add)

    remove = subparsers.add_parser("remove", help="unregister an account and delete its login dir")
    remove.add_argument("name", help="account name")
    remove.set_defaults(handler=_cmd_remove)

    list_parser = subparsers.add_parser("list", help="list registered accounts")
    list_parser.add_argument("--json", action="store_true", help="emit the schema-v1 JSON payload")
    list_parser.set_defaults(handler=_cmd_list)
    status_parser = subparsers.add_parser(
        "status", help="show the account the live claude slot uses"
    )
    status_parser.add_argument(
        "--json", action="store_true", help="emit the schema-v1 JSON payload"
    )
    status_parser.set_defaults(handler=_cmd_status)

    usage = subparsers.add_parser("usage", help="show one account's quota usage")
    usage.add_argument("name", help="account name")
    usage.add_argument("--json", action="store_true", help="emit the schema-v1 JSON payload")
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
    switch.add_argument("--json", action="store_true", help="emit the schema-v1 JSON payload")
    switch.add_argument(
        "--model",
        help="model preference for cam auto — accepted but not persisted yet",
    )
    switch.set_defaults(handler=_cmd_switch)

    disable = subparsers.add_parser("disable", help="hold an account out of automatic switching")
    disable.add_argument("name", help="account name")
    disable.set_defaults(handler=_cmd_disable)

    enable = subparsers.add_parser(
        "enable", help="return a disabled account to automatic switching"
    )
    enable.add_argument("name", help="account name")
    enable.set_defaults(handler=_cmd_enable)
    return parser


def _error_envelope(error_type: str, message: str) -> dict[str, object]:
    """The schema-v1 failure object — ``error.type`` is the stable tag."""
    return {
        "schemaVersion": SCHEMA_VERSION,
        "error": {"type": error_type, "message": message},
    }


def _emit_error(error_type: str, message: str, args: argparse.Namespace) -> int:
    """Route a handled failure: JSON envelope on stdout, else stderr text."""
    if args.json:
        print(json.dumps(_error_envelope(error_type, message), indent=2))
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
