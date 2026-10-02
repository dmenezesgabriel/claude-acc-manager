"""The schema-v1 JSON contract — payload builders only, no printing.

Every ``--json`` command projects its result through a builder here; the
single ``json.dumps`` lives in ``dispatch.run``. The switch-outcome
wording lives in ``accounts.application.switch_message`` — the CLI text
render, this JSON ``message`` field, and the TUI toast share it so the
surfaces cannot drift.
"""

from datetime import UTC, datetime
from pathlib import Path

from claude_acc_manager.accounts.application.switch_message import switch_message
from claude_acc_manager.accounts.application.use_cases.list_accounts import AccountSummary
from claude_acc_manager.accounts.application.use_cases.status_account import (
    ActiveAccountStatus,
)
from claude_acc_manager.accounts.application.use_cases.switch_account import SwitchResult
from claude_acc_manager.cli.context import UseCases
from claude_acc_manager.settings.domain.settings_spec import EffectiveSetting
from claude_acc_manager.usage.application.use_cases.fetch_account_usage import UsageReport
from claude_acc_manager.usage.domain.services import cache_trust, poll_policy
from claude_acc_manager.usage.domain.usage_cache_entry import UsageCacheEntry
from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot

SCHEMA_VERSION = 1


def error_envelope(error_type: str, message: str) -> dict[str, object]:
    """The schema-v1 failure object — ``error.type`` is the stable tag."""
    return {
        "schemaVersion": SCHEMA_VERSION,
        "error": {"type": error_type, "message": message},
    }


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


def usage_payload(account: str, report: UsageReport, quarantined: bool) -> dict[str, object]:
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


def list_payload(summaries: list[AccountSummary], use_cases: UseCases) -> dict[str, object]:
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


def status_payload(status: ActiveAccountStatus | None, use_cases: UseCases) -> dict[str, object]:
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


def switch_payload(
    result: SwitchResult, strategy: str | None, use_cases: UseCases
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
        "strategy": strategy,
        "skipped": [{"name": c.name, "reason": c.reason} for c in result.skipped],
        "quarantined": list(result.quarantined),
        "message": switch_message(result),
    }


def _account_ref(name: str | None, emails: dict[str, str]) -> dict[str, object] | None:
    """A switch endpoint as ``{name, email}`` — ``None`` for no account."""
    if name is None:
        return None
    return {"name": name, "email": emails[name]}


def config_get_payload(row: EffectiveSetting) -> dict[str, object]:
    """The schema-v1 ``config get --json`` projection of one setting row."""
    return {
        "schemaVersion": SCHEMA_VERSION,
        "key": row.spec.dotted,
        "value": row.value,
        "isSet": row.is_set,
    }


def config_list_payload(rows: tuple[EffectiveSetting, ...], path: Path) -> dict[str, object]:
    """The schema-v1 ``config list --json`` payload — every key, file path."""
    return {
        "schemaVersion": SCHEMA_VERSION,
        "path": str(path),
        "settings": [
            {"key": row.spec.dotted, "value": row.value, "isSet": row.is_set} for row in rows
        ],
    }
