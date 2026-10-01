"""registry.json persistence for accounts (docs/architecture.md §3).

Schema v1 (snake_case, this tool's own file):
{"schemaVersion": 1, "order": [...], "active": name|null,
 "accounts": {name: {email, account_uuid, organization_uuid,
                     organization_name, added_at, enabled}},
 "quarantined": [...]}
Drift (unknown/missing fields, wrong types, wrong version) fails loudly
(docs/architecture.md §11). Mutations run under the store's flock spanning read→write
(ai-usagebar active.rs discipline); reads are lock-free because atomic
rename guarantees whole-file consistency.
"""

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import NamedTuple, TypedDict, cast

from claude_acc_manager.accounts.application.ports import AccountStorePort
from claude_acc_manager.accounts.domain.entities import Account, QuarantineEntry
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.shared import fsio
from claude_acc_manager.shared.file_lock import exclusive_file_lock

SCHEMA_VERSION = 1

_RECORD_KEYS = (
    "email",
    "account_uuid",
    "organization_uuid",
    "organization_name",
    "added_at",
    "enabled",
)
_DOCUMENT_KEYS = (
    "schemaVersion",
    "order",
    "active",
    "accounts",
    "quarantined",
)


class TypedAccountRecord(TypedDict):
    """registry.json's per-account record shape."""

    email: str
    account_uuid: str
    organization_uuid: str | None
    organization_name: str | None
    added_at: str
    enabled: bool


class TypedQuarantineRecord(TypedDict):
    """registry.json's quarantined[] entry shape."""

    name: str
    reason: str
    at: str
    refresh_token_fingerprint: str | None


class TypedRegistryDocument(TypedDict):
    """registry.json's top-level shape."""

    schemaVersion: int
    order: list[str]
    active: str | None
    accounts: dict[str, TypedAccountRecord]
    quarantined: list[TypedQuarantineRecord]


class _RegistryState(NamedTuple):
    """In-memory shape of registry.json."""

    accounts: dict[str, Account]
    order: list[str]
    active: str | None
    quarantined: list[QuarantineEntry]


def _record_from(account: Account) -> TypedAccountRecord:
    return {
        "email": account.email,
        "account_uuid": account.account_uuid,
        "organization_uuid": account.organization_uuid,
        "organization_name": account.organization_name,
        "added_at": account.added_at,
        "enabled": account.enabled,
    }


def _object_map(value: object, error: str) -> dict[str, object]:
    """Narrow an untyped JSON object to dict[str, object] or raise *error*.

    # pragma: no mutate justification: cast() is a runtime no-op — its type
    # argument is consumed by type checkers only, so mutants of it are
    # equivalent by construction.
    """
    if not isinstance(value, dict):
        raise ValueError(error)
    return cast("dict[str, object]", value)  # pragma: no mutate


def _object_list(value: object, error: str) -> list[object]:
    """Narrow an untyped JSON list or raise *error* (same cast rationale)."""
    if not isinstance(value, list):
        raise ValueError(error)
    return cast("list[object]", value)  # pragma: no mutate


def _str_list(value: object, error: str) -> list[str]:
    """Narrow to a list whose every element is a str, else raise *error*."""
    result: list[str] = []
    for name in _object_list(value, error):
        if not isinstance(name, str):
            raise ValueError(error)
        result.append(name)
    return result


def _require_str(name: str, key: str, value: object) -> str:
    if not isinstance(value, str):
        raise ValueError(f"registry record '{name}': {key} must be a str, got {value!r}")
    return value


def _require_optional_str(name: str, key: str, value: object) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError(f"registry record '{name}': {key} must be a str or null, got {value!r}")
    return value if isinstance(value, str) else None


def _account_from(name: str, record: object) -> Account:
    record_map = _object_map(
        record, f"registry record '{name}' must be a JSON object, got {record!r}"
    )
    unknown = [key for key in record_map if key not in _RECORD_KEYS]
    if unknown:
        raise ValueError(f"registry record '{name}' has unknown fields {unknown}")
    missing = [key for key in _RECORD_KEYS if key not in record_map]
    if missing:
        raise ValueError(f"registry record '{name}' is missing fields {missing}")
    enabled = record_map["enabled"]
    if not isinstance(enabled, bool):
        raise ValueError(f"registry record '{name}': enabled must be a bool, got {enabled!r}")
    return Account(
        name=AccountName(name),
        email=_require_str(name, "email", record_map["email"]),
        account_uuid=_require_str(name, "account_uuid", record_map["account_uuid"]),
        organization_uuid=_require_optional_str(
            name, "organization_uuid", record_map["organization_uuid"]
        ),
        organization_name=_require_optional_str(
            name, "organization_name", record_map["organization_name"]
        ),
        added_at=_require_str(name, "added_at", record_map["added_at"]),
        enabled=enabled,
    )


class _ValidatedDocument(NamedTuple):
    """Shape-checked registry parts (schemaVersion is not read again)."""

    accounts: dict[str, object]
    order: list[str]
    active: str | None
    quarantined: list[object]


def _validate_keys(document_map: dict[str, object]) -> None:
    """Reject unknown and missing top-level fields (schema drift surfaces)."""
    unknown = [key for key in document_map if key not in _DOCUMENT_KEYS]
    if unknown:
        raise ValueError(f"registry has unknown top-level fields {unknown}")
    missing = [key for key in _DOCUMENT_KEYS if key not in document_map]
    if missing:
        raise ValueError(f"registry is missing top-level fields {missing}")


def _validate_version(version: object) -> None:
    # bool is a subclass of int (True == 1), so a bare int check would let a
    # JSON true pass as schema version 1
    if not isinstance(version, int) or isinstance(version, bool) or version != SCHEMA_VERSION:
        raise ValueError(
            f"registry schemaVersion {version!r} is not supported (expected {SCHEMA_VERSION})"
        )


def _validate_document(document: object) -> _ValidatedDocument:
    """Check the top-level shape; returns the validated parts."""
    document_map = _object_map(document, f"registry must be a JSON object, got {document!r}")
    _validate_keys(document_map)
    _validate_version(document_map["schemaVersion"])
    accounts_map = _object_map(
        document_map["accounts"],
        f"registry accounts must be a JSON object, got {document_map['accounts']!r}",
    )
    order = _str_list(
        document_map["order"],
        f"registry order must be a list of names, got {document_map['order']!r}",
    )
    active = document_map["active"]
    if active is not None and not isinstance(active, str):
        raise ValueError(f"registry active must be a name or null, got {active!r}")
    quarantined = _object_list(
        document_map["quarantined"],
        f"registry quarantined must be a list, got {document_map['quarantined']!r}",
    )
    return _ValidatedDocument(
        accounts=accounts_map,
        order=order,
        active=active,
        quarantined=quarantined,
    )


_QUARANTINE_KEYS = ("name", "reason", "at", "refresh_token_fingerprint")


def _quarantine_entry_from(item: object) -> QuarantineEntry:
    """Parse one quarantined[] entry; every field checked, drift named."""
    item_map = _object_map(item, f"registry quarantined entry {item!r} must be a JSON object")
    prefix = f"registry quarantined entry {item_map.get('name', item)!r}"
    unknown = [key for key in item_map if key not in _QUARANTINE_KEYS]
    if unknown:
        raise ValueError(f"{prefix} has unknown fields {unknown}")
    missing = [key for key in _QUARANTINE_KEYS if key not in item_map]
    if missing:
        raise ValueError(f"{prefix} is missing fields {missing}")

    def required(key: str) -> str:
        value = item_map[key]
        if not isinstance(value, str):
            raise ValueError(f"{prefix}: {key} must be a str, got {value!r}")
        return value

    fingerprint = item_map["refresh_token_fingerprint"]
    if fingerprint is not None and not isinstance(fingerprint, str):
        raise ValueError(
            f"{prefix}: refresh_token_fingerprint must be a str or null, got {fingerprint!r}"
        )
    return QuarantineEntry(
        name=required("name"),
        reason=required("reason"),
        at=required("at"),
        refresh_token_fingerprint=fingerprint,
    )


def _quarantine_record_from(entry: QuarantineEntry) -> TypedQuarantineRecord:
    return {
        "name": entry.name,
        "reason": entry.reason,
        "at": entry.at,
        "refresh_token_fingerprint": entry.refresh_token_fingerprint,
    }


def _registry_from(document: object) -> _RegistryState:
    validated = _validate_document(document)
    accounts = {name: _account_from(name, record) for name, record in validated.accounts.items()}
    for name in validated.order:
        if name not in accounts:
            raise ValueError(f"registry order references unknown account {name!r}")
    return _RegistryState(
        accounts=accounts,
        order=validated.order,
        active=validated.active,
        quarantined=[_quarantine_entry_from(item) for item in validated.quarantined],
    )


def _document_from(state: _RegistryState) -> TypedRegistryDocument:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "order": state.order,
        "active": state.active,
        "accounts": {name: _record_from(account) for name, account in state.accounts.items()},
        "quarantined": [_quarantine_record_from(e) for e in state.quarantined],
    }


class FileAccountStore(AccountStorePort):
    """AccountStorePort over a 0600 atomic registry.json (docs/architecture.md §3).

    All paths are injected through *store_root* so callers and tests run
    hermetically; nothing is read from ambient environment state.

    Example:
        store = FileAccountStore(store_root=Path("~/.local/share/cam"))
        store.upsert(account)
    """

    def __init__(self, store_root: Path) -> None:
        """Store at *store_root*: registry.json + .lock live there directly."""
        self._store_root = store_root
        self._registry_path = store_root / "registry.json"
        self._lock_path = store_root / ".lock"

    def _read(self) -> _RegistryState:
        if not self._registry_path.exists():
            return _RegistryState(accounts={}, order=[], active=None, quarantined=[])
        # json.loads on bytes auto-detects utf-8: keeps the read codec in one
        # place instead of an unobservable encoding literal
        return _registry_from(json.loads(self._registry_path.read_bytes()))

    def _mutate(self, apply: Callable[[_RegistryState], _RegistryState]) -> None:
        """Read-modify-write the registry under the store's exclusive lock."""
        fsio.ensure_private_dir(self._store_root)
        with exclusive_file_lock(self._lock_path):
            new_state = apply(self._read())
            fsio.atomic_write_json(self._registry_path, _document_from(new_state))

    def upsert(self, account: Account) -> None:
        """Insert or update, appending to the order when new (port contract)."""

        def apply(state: _RegistryState) -> _RegistryState:
            is_new = account.name.value not in state.accounts
            accounts = dict(state.accounts)
            accounts[account.name.value] = account
            order = state.order if not is_new else [*state.order, account.name.value]
            return state._replace(accounts=accounts, order=order)

        self._mutate(apply)

    def remove(self, name: AccountName) -> None:
        """Drop record, order entry, active pointer, and tombstone."""

        def apply(state: _RegistryState) -> _RegistryState:
            if name.value not in state.accounts:
                raise KeyError(name.value)
            accounts = {k: v for k, v in state.accounts.items() if k != name.value}
            order = [entry for entry in state.order if entry != name.value]
            active = None if state.active == name.value else state.active
            quarantined = [e for e in state.quarantined if e.name != name.value]
            return state._replace(
                accounts=accounts, order=order, active=active, quarantined=quarantined
            )

        self._mutate(apply)

    def get(self, name: AccountName) -> Account | None:
        """The account, or None when unknown (port contract)."""
        return self._read().accounts.get(name.value)

    def list_accounts(self) -> list[Account]:
        """All accounts in registry order (port contract)."""
        state = self._read()
        return [state.accounts[name] for name in state.order]

    def set_enabled(self, name: AccountName, enabled: bool) -> None:
        """Persist the enabled flag (port contract)."""

        def apply(state: _RegistryState) -> _RegistryState:
            if name.value not in state.accounts:
                raise KeyError(name.value)
            current = state.accounts[name.value]
            return state._replace(
                accounts={**state.accounts, name.value: replace(current, enabled=enabled)}
            )

        self._mutate(apply)

    def quarantined(self) -> list[QuarantineEntry]:
        """Every dead-lineage tombstone, in record order (port contract)."""
        return list(self._read().quarantined)

    def set_quarantined(self, entry: QuarantineEntry) -> None:
        """Record or replace *entry.name*'s tombstone (port contract)."""

        def apply(state: _RegistryState) -> _RegistryState:
            if entry.name not in state.accounts:
                raise KeyError(entry.name)
            kept = [e for e in state.quarantined if e.name != entry.name]
            return state._replace(quarantined=[*kept, entry])

        self._mutate(apply)

    def clear_quarantined(self, name: AccountName) -> None:
        """Drop *name*'s tombstone; no-op when it has none (port contract)."""

        def apply(state: _RegistryState) -> _RegistryState:
            kept = [e for e in state.quarantined if e.name != name.value]
            return state._replace(quarantined=kept)

        self._mutate(apply)

    def set_active(self, name: AccountName | None) -> None:
        """Point the active slot at *name*, or unset with None (port contract)."""
        self._mutate(lambda state: state._replace(active=name.value if name else None))

    def active(self) -> Account | None:
        """The active account; None when unset or dangling (port contract)."""
        state = self._read()
        if state.active is None:
            return None
        return state.accounts.get(state.active)

    def account_dir(self, name: AccountName) -> Path:
        """The account's isolated CLAUDE_CONFIG_DIR (docs/architecture.md §3).

        Derived from the store root — the store owns the layout.
        """
        return self._store_root / "accounts" / name.value
