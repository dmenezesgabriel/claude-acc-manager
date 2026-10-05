"""The ``_cmd_*`` handlers — orchestrate a use case, render the outcome.

Each handler returns ``int`` for the exit code, or the schema-v1 dict under
``--json`` (``dispatch.run`` owns the one ``json.dumps``). Human wording is
the interface; the pinned strings live in ``test/unit/test_cli.py``.
"""

import argparse
import signal
from types import FrameType
from typing import cast

from claude_acc_manager.accounts.application.doctor_report import DoctorCheck
from claude_acc_manager.accounts.application.ports import SwitchResult
from claude_acc_manager.accounts.application.switch_message import switch_message
from claude_acc_manager.accounts.domain.services.switch_selection import SwitchStrategy
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.auto.application.auto_engine import AutoEngine
from claude_acc_manager.cli.auto_output import auto_emit, banner_text
from claude_acc_manager.cli.context import UseCases
from claude_acc_manager.cli.human import (
    ACCENT_STYLE,
    EMPHASIS_STYLE,
    ERR_STYLE,
    MUTED_STYLE,
    WARN_STYLE,
    HumanOutput,
)
from claude_acc_manager.cli.json_output import (
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
from claude_acc_manager.usage.application.use_cases.fetch_account_usage import UsageReport
from claude_acc_manager.usage.domain.services.headroom import account_headroom


def cmd_add(args: argparse.Namespace, use_cases: UseCases, out: HumanOutput) -> int:
    """Register the account via an isolated login; print the confirmation."""
    use_cases.add.execute(AccountName(args.name))
    out.print(out.styled(f"added account {args.name!r}", EMPHASIS_STYLE))
    return 0


def cmd_remove(args: argparse.Namespace, use_cases: UseCases, out: HumanOutput) -> int:
    """Unregister the account and its login dir; print the confirmation."""
    use_cases.remove.execute(AccountName(args.name))
    out.print(out.styled(f"removed account {args.name!r}", EMPHASIS_STYLE))
    return 0


def cmd_list(
    args: argparse.Namespace, use_cases: UseCases, out: HumanOutput
) -> int | dict[str, object]:
    """List registered accounts — marked rows, or the schema-v1 payload."""
    summaries = use_cases.list_accounts.execute()
    if args.json:
        return list_payload(summaries, use_cases)
    if not summaries:
        out.print("no accounts registered")
        return 0
    for summary in summaries:
        marker = out.styled("*", ACCENT_STYLE) if summary.is_active else " "
        row = f"{marker} {summary.account.name.value}\t{summary.account.email}"
        if not summary.account.enabled:
            row += out.styled(" [disabled]", MUTED_STYLE)
        if summary.is_quarantined:
            row += out.styled(" [quarantined]", WARN_STYLE)
        out.print(row)
    return 0


def cmd_status(
    args: argparse.Namespace, use_cases: UseCases, out: HumanOutput
) -> int | dict[str, object]:
    """Show the live login — one line, or the schema-v1 payload."""
    status = use_cases.status.execute()
    if args.json:
        return status_payload(status, use_cases)
    if status is None:
        out.print("no account is logged in")
        return 0
    where = f"managed as {status.managed_as!r}" if status.managed_as else "not managed"
    out.print(f"logged in as {status.email} ({where})")
    return 0


def _print_usage_report(report: UsageReport, out: HumanOutput) -> None:
    if report.snapshot is None:
        out.print(out.styled(f"usage unknown: {report.last_error}", MUTED_STYLE))
        return
    if report.snapshot.five_hour is not None:
        out.print(f"five_hour: {_severity_pct(report.snapshot.five_hour.pct, out)}")
    if report.snapshot.seven_day is not None:
        out.print(f"seven_day: {_severity_pct(report.snapshot.seven_day.pct, out)}")
    for scoped in report.snapshot.scoped:
        out.print(f"{scoped.name}: {_severity_pct(scoped.pct, out)}")
    if report.stale:
        out.print(out.styled(f"(stale: {report.last_error})", MUTED_STYLE))


def _severity_pct(pct: float, out: HumanOutput) -> str:
    """One ``N%`` fragment colored by the shared WARN/CRIT ramp."""
    return out.styled(f"{pct:.0f}%", out.severity_style(pct))


def cmd_usage(
    args: argparse.Namespace, use_cases: UseCases, out: HumanOutput
) -> int | dict[str, object]:
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
    _print_usage_report(report, out)
    if quarantined:
        out.print(
            out.styled(
                f"quarantined {name.value!r}: the provider permanently rejected its refresh token",
                WARN_STYLE,
            )
        )
    return 0


def _cached_headroom(use_cases: UseCases) -> dict[str, float | None]:
    """Per-account headroom from the usage cache (``None`` = unmeasured)."""
    return {
        account.name.value: account_headroom(
            use_cases.usage_cache.load(account.name.value).last_good
        )
        for account in use_cases.account_store.list_accounts()
    }


def cmd_switch(
    args: argparse.Namespace, use_cases: UseCases, out: HumanOutput
) -> int | dict[str, object]:
    """Switch the live login — text render, or the schema-v1 payload."""
    target = AccountName(args.name) if args.name else None
    if target is not None and use_cases.account_store.get(target) is None:
        raise KeyError(target.value)
    # argparse's choices= binds args.strategy to a non-empty literal or None —
    # no falsy non-None value exists, so `or True` is equivalent (as below).
    headroom = _cached_headroom(use_cases) if args.strategy else None  # pragma: no mutate
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
    _print_switch_result(result, out)
    return 0


def _print_switch_result(result: SwitchResult, out: HumanOutput) -> None:
    """Render the switch outcome; the printed wording is the interface."""
    prefix = "dry run: " if result.dry_run else ""
    message = switch_message(result)
    if result.outcome == "switched":
        message = out.styled(message, EMPHASIS_STYLE)
    out.print(message)
    if result.outcome == "switched":
        _print_switch_notes(result, prefix, out)
    for candidate in result.skipped:
        out.print(
            out.styled(f"{prefix}skipped {candidate.name!r}: {candidate.reason}", MUTED_STYLE)
        )


def _print_switch_notes(result: SwitchResult, prefix: str, out: HumanOutput) -> None:
    """The preservation/quarantine notes that follow a real switch line."""
    if result.unmanaged_live:
        where = result.preserved_to if result.preserved_to else "unclaimed/"
        out.print(
            out.styled(
                f"{prefix}the previous unmanaged login was preserved under {where}", MUTED_STYLE
            )
        )
    for name in result.quarantined:
        out.print(out.styled(f"{prefix}quarantined the wiped credential of {name!r}", WARN_STYLE))


def cmd_tui(args: argparse.Namespace, use_cases: UseCases, out: HumanOutput) -> int:
    """Launch the interactive dashboard (textual imports stay lazy)."""
    from claude_acc_manager.tui import run as run_tui

    return run_tui(use_cases, start="dashboard")


def cmd_watch(args: argparse.Namespace, use_cases: UseCases, out: HumanOutput) -> int:
    """Launch the TUI directly on the watch screen."""
    from claude_acc_manager.tui import run as run_tui

    return run_tui(use_cases, start="watch")


def cmd_disable(args: argparse.Namespace, use_cases: UseCases, out: HumanOutput) -> int:
    """Hold the account out of automatic switching."""
    return _set_enabled(args, use_cases, out, enabled=False)


def cmd_enable(args: argparse.Namespace, use_cases: UseCases, out: HumanOutput) -> int:
    """Return a disabled account to automatic switching."""
    return _set_enabled(args, use_cases, out, enabled=True)


def _set_enabled(
    args: argparse.Namespace, use_cases: UseCases, out: HumanOutput, enabled: bool
) -> int:
    """Toggle the account and print the confirmation plus safety notes."""
    name = AccountName(args.name)
    account = use_cases.account_store.get(name)
    if account is None:
        raise KeyError(name.value)
    verb = "enabled" if enabled else "disabled"
    if account.enabled == enabled:
        out.print(f"account {name.value!r} is already {verb}")
        return 0
    use_cases.set_enabled.execute(name, enabled)
    out.print(out.styled(f"{verb} account {name.value!r}", EMPHASIS_STYLE))
    if enabled:
        out.print("  it is back in the rotation")
        return 0
    _print_disable_notes(name.value, use_cases, out)
    return 0


def _print_disable_notes(name: str, use_cases: UseCases, out: HumanOutput) -> None:
    """The footgun warnings that follow a disable."""
    active = use_cases.account_store.active()
    if active is not None and active.name.value == name:
        out.print(
            f"  note: {name!r} is the active account — it stays live until you "
            "switch away; it just won't be an automatic switch target"
        )
    if not any(account.enabled for account in use_cases.account_store.list_accounts()):
        out.print(
            "  warning: no enabled accounts remain in rotation — automatic "
            "switching has nothing to pick (re-enable one with cam enable <name>)"
        )


def cmd_config_list(
    args: argparse.Namespace, use_cases: UseCases, out: HumanOutput
) -> int | dict[str, object]:
    """Every spec key's effective row — aligned text, or the schema-v1 payload."""
    rows = use_cases.list_settings.execute()
    if args.json:
        return config_list_payload(rows, use_cases.settings.path)
    key_w = max(len(row.spec.dotted) for row in rows)
    val_w = max(len(format_setting_value(row.value)) for row in rows)
    for row in rows:
        line = f"{row.spec.dotted:<{key_w}}  {format_setting_value(row.value):<{val_w}}"
        out.print(line if row.is_set else f"{line}  (default)")
    return 0


def cmd_config_get(
    args: argparse.Namespace, use_cases: UseCases, out: HumanOutput
) -> int | dict[str, object]:
    """One key's effective value — bare for scripting, or the schema-v1 payload."""
    spec = setting_spec(args.key)
    row = next(row for row in use_cases.list_settings.execute() if row.spec is spec)
    if args.json:
        return config_get_payload(row)
    out.print(format_setting_value(row.value))
    return 0


def cmd_config_set(args: argparse.Namespace, use_cases: UseCases, out: HumanOutput) -> int:
    """Validate-then-persist one key; strict errors surface here, not at auto time."""
    value = use_cases.set_setting.execute(args.key, args.value)
    out.print(out.styled(f"{args.key} = {format_setting_value(value)}", EMPHASIS_STYLE))
    return 0


def cmd_config_unset(args: argparse.Namespace, use_cases: UseCases, out: HumanOutput) -> int:
    """Remove one key so the default governs; a no-op removal says so on stderr."""
    spec = setting_spec(args.key)
    if use_cases.unset_setting.execute(args.key):
        out.print(
            out.styled(
                f"{args.key} unset (default: {format_setting_value(spec_default(spec))})",
                EMPHASIS_STYLE,
            )
        )
        return 0
    out.error(f"{args.key} is not set; nothing to do")
    return 0


def cmd_config_path(args: argparse.Namespace, use_cases: UseCases, out: HumanOutput) -> int:
    """Print where settings.json lives."""
    out.print(str(use_cases.settings.path))
    return 0


# -- cam auto -------------------------------------------------------------------

# argparse dests double as AutoSettings field names — ``strict_override``
# looks each up in the spec table, so a flag must name a spec field.
_AUTO_FLAG_FIELDS = ("interval_seconds", "threshold", "cooldown_seconds", "strategy")


def cmd_auto(args: argparse.Namespace, use_cases: UseCases, out: HumanOutput) -> int:
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
        emit=auto_emit(args.json, clock, out),
        dry_run=args.dry_run,
    )
    if args.once:
        return engine.tick().value

    def _on_sigterm(_signum: int, _frame: FrameType | None) -> None:
        engine.stop()

    signal.signal(signal.SIGTERM, _on_sigterm)
    if not args.json:
        out.print(banner_text(settings, args.dry_run))
    return engine.run_loop()


_STATUS_STYLES = {"ok": "green", "warn": WARN_STYLE, "fail": ERR_STYLE}


def cmd_doctor(args: argparse.Namespace, use_cases: UseCases, out: HumanOutput) -> int:
    """Render the diagnostics report; findings don't gate the exit code.

    Exit 0 whenever the report renders — the contract refusal already lives
    in every mutating op; doctor's job is to show it.
    """
    report = use_cases.diagnostics.execute()
    for section in report.sections:
        out.print(out.styled(section.title, EMPHASIS_STYLE))
        for check in section.checks:
            out.print(f"  {check.name}: {_check_value(check, out)}")
    return 0


def _check_value(check: DoctorCheck, out: HumanOutput) -> str:
    """The badge + value for a verdict row; plain value for info rows."""
    if check.status == "info":
        return check.value
    badge = out.styled(f"[{check.status.upper()}]", _STATUS_STYLES[check.status])
    return f"{badge} {check.value}"


def _auto_settings(args: argparse.Namespace, use_cases: UseCases) -> AutoSettings:
    """settings.json under the CLI flags — a flag out of range fails loudly."""
    overrides = {
        field: getattr(args, field)
        for field in _AUTO_FLAG_FIELDS
        if getattr(args, field) is not None
    }
    return strict_override(use_cases.load_settings.execute(), overrides)
