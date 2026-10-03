"""The ``_cmd_*`` handlers — orchestrate a use case, render the outcome.

Each handler returns ``int`` for the exit code, or the schema-v1 dict under
``--json`` (``dispatch.run`` owns the one ``json.dumps``). Human wording is
the interface; the pinned strings live in ``test/unit/test_cli.py``.
"""

import argparse
import datetime as dt
import json
import signal
import sys
from collections.abc import Callable
from types import FrameType
from typing import cast

from claude_acc_manager.accounts.application.ports import SwitchResult
from claude_acc_manager.accounts.application.switch_message import switch_message
from claude_acc_manager.accounts.domain.services.switch_selection import SwitchStrategy
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.auto.application.auto_engine import AutoEngine
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
from claude_acc_manager.cli.context import UseCases
from claude_acc_manager.cli.json_output import (
    auto_event_json,
    config_get_payload,
    config_list_payload,
    list_payload,
    status_payload,
    switch_payload,
    usage_payload,
)
from claude_acc_manager.settings.domain.settings_spec import (
    AutoSettings,
    format_setting_value,
    setting_spec,
    spec_default,
    strict_override,
)
from claude_acc_manager.usage.application.ports import ClockPort
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
    # args.model is accepted for flag parity but not persisted — model-scoped
    # windows are out of the auto settings surface (ADR-0006).
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


def cmd_tui(args: argparse.Namespace, use_cases: UseCases) -> int:
    """Launch the interactive dashboard (textual imports stay lazy)."""
    from claude_acc_manager.tui import run as run_tui

    return run_tui(use_cases, start="dashboard")


def cmd_watch(args: argparse.Namespace, use_cases: UseCases) -> int:
    """Launch the TUI directly on the watch screen."""
    from claude_acc_manager.tui import run as run_tui

    return run_tui(use_cases, start="watch")


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


def cmd_config_list(args: argparse.Namespace, use_cases: UseCases) -> int | dict[str, object]:
    """Every spec key's effective row — aligned text, or the schema-v1 payload."""
    rows = use_cases.list_settings.execute()
    if args.json:
        return config_list_payload(rows, use_cases.settings.path)
    key_w = max(len(row.spec.dotted) for row in rows)
    val_w = max(len(format_setting_value(row.value)) for row in rows)
    for row in rows:
        line = f"{row.spec.dotted:<{key_w}}  {format_setting_value(row.value):<{val_w}}"
        print(line if row.is_set else f"{line}  (default)")
    return 0


def cmd_config_get(args: argparse.Namespace, use_cases: UseCases) -> int | dict[str, object]:
    """One key's effective value — bare for scripting, or the schema-v1 payload."""
    spec = setting_spec(args.key)
    row = next(row for row in use_cases.list_settings.execute() if row.spec is spec)
    if args.json:
        return config_get_payload(row)
    print(format_setting_value(row.value))
    return 0


def cmd_config_set(args: argparse.Namespace, use_cases: UseCases) -> int:
    """Validate-then-persist one key; strict errors surface here, not at auto time."""
    value = use_cases.set_setting.execute(args.key, args.value)
    print(f"{args.key} = {format_setting_value(value)}")
    return 0


def cmd_config_unset(args: argparse.Namespace, use_cases: UseCases) -> int:
    """Remove one key so the default governs; a no-op removal says so on stderr."""
    spec = setting_spec(args.key)
    if use_cases.unset_setting.execute(args.key):
        print(f"{args.key} unset (default: {format_setting_value(spec_default(spec))})")
        return 0
    print(f"{args.key} is not set; nothing to do", file=sys.stderr)
    return 0


def cmd_config_path(args: argparse.Namespace, use_cases: UseCases) -> int:
    """Print where settings.json lives."""
    print(use_cases.settings.path)
    return 0


# -- cam auto -------------------------------------------------------------------

# argparse dests double as AutoSettings field names — ``strict_override``
# looks each up in the spec table, so a flag must name a spec field.
_AUTO_FLAG_FIELDS = ("interval_seconds", "threshold", "cooldown_seconds", "strategy")


def cmd_auto(args: argparse.Namespace, use_cases: UseCases) -> int:
    """Run the engine — one tick under ``--once``, else the foreground loop.

    The tick's ``TickOutcome`` is the process exit code (0 switched, 1
    error, 2 no action, 3 blocked). Loop mode installs the SIGTERM→
    ``engine.stop()`` handoff (systemd stop) and prints a startup banner
    unless ``--json`` (JSONL stdout purity).
    """
    settings = _auto_settings(args, use_cases)
    clock = use_cases.usage_clock
    engine = AutoEngine(
        settings=settings,
        active_identity=use_cases.status,
        store=use_cases.account_store,
        account_files=use_cases.account_files,
        usage_cache=use_cases.usage_cache,
        fetch=use_cases.fetch_usage,
        freshen=use_cases.freshen_target,
        quarantine=use_cases.quarantine_dead_lineage,
        switch_executor=use_cases.switch,
        auto_state=use_cases.auto_state,
        clock=clock,
        emit=_auto_emit(args.json, clock),
        dry_run=args.dry_run,
    )
    if args.once:
        return engine.tick().value

    def _on_sigterm(_signum: int, _frame: FrameType | None) -> None:
        engine.stop()

    signal.signal(signal.SIGTERM, _on_sigterm)
    if not args.json:
        print(
            f"auto-switch running: threshold {settings.threshold:g}%, "
            f"every {settings.interval_seconds:g}s"
            f"{' (dry-run)' if args.dry_run else ''} — Ctrl-C to stop"
        )
    return engine.run_loop()


def _auto_settings(args: argparse.Namespace, use_cases: UseCases) -> AutoSettings:
    """settings.json under the CLI flags — a flag out of range fails loudly."""
    overrides = {
        field: getattr(args, field)
        for field in _AUTO_FLAG_FIELDS
        if getattr(args, field) is not None
    }
    return strict_override(use_cases.load_settings.execute(), overrides)


def _auto_emit(json_mode: bool, clock: ClockPort) -> Callable[[AutoEvent], None]:
    """The event sink — JSONL one-per-line, or timestamped human text."""
    if json_mode:
        return lambda event: print(
            json.dumps(auto_event_json(event, _iso(clock.now_epoch_s()))), flush=True
        )
    return lambda event: print(f"{_stamp(clock)}  {_auto_event_line(event)}", flush=True)


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


def _auto_event_line(event: AutoEvent) -> str:
    """One human line per event kind."""
    if isinstance(event, PollEvent):
        return _poll_line(event)
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


def _poll_line(event: PollEvent) -> str:
    """The per-tick census: active utilization plus each parked account."""
    if event.active is None:
        return "poll: no active account"
    headroom = event.headroom.get(event.active)
    if headroom is not None:
        used = f"{100 - headroom:.0f}% used"
    else:
        err = event.fetch_errors.get(event.active)
        used = f"usage unknown ({err})" if err else "usage unknown"
    others = ", ".join(
        f"{name}: {_poll_describe(event, name)}" for name in event.headroom if name != event.active
    )
    tail = f" | others: {others}" if others else ""
    return f"{event.active}: {used} (switch at {event.threshold:g}%){tail}"


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
