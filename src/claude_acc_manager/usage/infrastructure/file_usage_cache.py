"""usage-cache.json persistence for the usage cache (plan §4.3).

Schema v1 (this tool's own file, not a mirror of the Anthropic wire shape):
{"schemaVersion": 1,
 "accounts": {name: {last_good: {five_hour, seven_day, scoped} | null,
                      fetched_at_s, consecutive_failures, last_error,
                      backoff_until_s, last_429_at_s, next_poll_at_s,
                      poll_interval_s}}}
Drift (unknown/missing fields, wrong types, wrong version) fails loudly
(plan §11), same discipline as accounts' file_account_store.py. Mutations
run under the store's single flock (plan §4.3: one .lock file governs every
mutation this tool makes, shared with FileAccountStore); an unknown account
key is not drift — it simply has never been cached, so ``load`` returns
EMPTY_USAGE_CACHE_ENTRY rather than raising.
"""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from claude_acc_manager.shared import fsio
from claude_acc_manager.shared.file_lock import exclusive_file_lock
from claude_acc_manager.usage.application.ports import UsageCachePort
from claude_acc_manager.usage.domain.usage_cache_entry import (
    EMPTY_USAGE_CACHE_ENTRY,
    UsageCacheEntry,
)
from claude_acc_manager.usage.domain.usage_snapshot import ScopedWindow, UsageSnapshot, UsageWindow

SCHEMA_VERSION = 1

_ENTRY_KEYS = (
    "last_good",
    "fetched_at_s",
    "consecutive_failures",
    "last_error",
    "backoff_until_s",
    "last_429_at_s",
    "next_poll_at_s",
    "poll_interval_s",
)
_WINDOW_KEYS = ("pct", "resets_at")
_SCOPED_KEYS = ("name", "pct", "resets_at")
_SNAPSHOT_KEYS = ("five_hour", "seven_day", "scoped")
_DOCUMENT_KEYS = ("schemaVersion", "accounts")


def _object_map(value: object, error: str) -> dict[str, object]:
    """Narrow an untyped JSON object to dict[str, object] or raise *error*.

    # pragma: no mutate justification: cast() is a runtime no-op — its type
    # argument is consumed by type checkers only, so mutants of it are
    # equivalent by construction (same reason file_account_store.py carries
    # this pragma).
    """
    if not isinstance(value, dict):
        raise ValueError(error)
    return cast("dict[str, object]", value)  # pragma: no mutate


def _require_number(context: str, key: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context}: {key} must be a number, got {value!r}")
    return float(value)


def _require_optional_number(context: str, key: str, value: object) -> float | None:
    if value is None:
        return None
    return _require_number(context, key, value)


def _require_str(context: str, key: str, value: object) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{context}: {key} must be a str, got {value!r}")
    return value


def _require_optional_str(context: str, key: str, value: object) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{context}: {key} must be a str or null, got {value!r}")
    return value


def _require_int(context: str, key: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{context}: {key} must be an int, got {value!r}")
    return value


def _require_keys(context: str, keys: tuple[str, ...], record: Mapping[str, object]) -> None:
    unknown = [key for key in record if key not in keys]
    if unknown:
        raise ValueError(f"{context} has unknown fields {unknown}")
    missing = [key for key in keys if key not in record]
    if missing:
        raise ValueError(f"{context} is missing fields {missing}")


def _window_to_json(window: UsageWindow | None) -> dict[str, object] | None:
    if window is None:
        return None
    return {"pct": window.pct, "resets_at": window.resets_at}


def _window_from_json(context: str, value: object) -> UsageWindow | None:
    if value is None:
        return None
    record = _object_map(value, f"{context} must be a JSON object or null, got {value!r}")
    _require_keys(context, _WINDOW_KEYS, record)
    return UsageWindow(
        pct=_require_number(context, "pct", record["pct"]),
        resets_at=_require_optional_str(context, "resets_at", record["resets_at"]),
    )


def _scoped_to_json(scoped: tuple[ScopedWindow, ...]) -> list[dict[str, object]]:
    return [
        {"name": window.name, "pct": window.pct, "resets_at": window.resets_at} for window in scoped
    ]


def _scoped_from_json(context: str, value: object) -> tuple[ScopedWindow, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be a list, got {value!r}")
    entries = cast("list[object]", value)  # pragma: no mutate — see _object_map
    windows: list[ScopedWindow] = []
    for index, entry in enumerate(entries):
        entry_context = f"{context}[{index}]"
        record = _object_map(entry, f"{entry_context} must be a JSON object, got {entry!r}")
        _require_keys(entry_context, _SCOPED_KEYS, record)
        windows.append(
            ScopedWindow(
                name=_require_str(entry_context, "name", record["name"]),
                pct=_require_number(entry_context, "pct", record["pct"]),
                resets_at=_require_optional_str(entry_context, "resets_at", record["resets_at"]),
            )
        )
    return tuple(windows)


def _snapshot_to_json(snapshot: UsageSnapshot | None) -> dict[str, object] | None:
    if snapshot is None:
        return None
    return {
        "five_hour": _window_to_json(snapshot.five_hour),
        "seven_day": _window_to_json(snapshot.seven_day),
        "scoped": _scoped_to_json(snapshot.scoped),
    }


def _snapshot_from_json(context: str, value: object) -> UsageSnapshot | None:
    if value is None:
        return None
    record = _object_map(value, f"{context} must be a JSON object or null, got {value!r}")
    _require_keys(context, _SNAPSHOT_KEYS, record)
    return UsageSnapshot(
        five_hour=_window_from_json(f"{context}.five_hour", record["five_hour"]),
        seven_day=_window_from_json(f"{context}.seven_day", record["seven_day"]),
        scoped=_scoped_from_json(f"{context}.scoped", record["scoped"]),
    )


def _entry_to_json(entry: UsageCacheEntry) -> dict[str, object]:
    return {
        "last_good": _snapshot_to_json(entry.last_good),
        "fetched_at_s": entry.fetched_at_s,
        "consecutive_failures": entry.consecutive_failures,
        "last_error": entry.last_error,
        "backoff_until_s": entry.backoff_until_s,
        "last_429_at_s": entry.last_429_at_s,
        "next_poll_at_s": entry.next_poll_at_s,
        "poll_interval_s": entry.poll_interval_s,
    }


def _entry_from_json(account_key: str, value: object) -> UsageCacheEntry:
    context = f"usage cache entry {account_key!r}"
    record = _object_map(value, f"{context} must be a JSON object, got {value!r}")
    _require_keys(context, _ENTRY_KEYS, record)
    return UsageCacheEntry(
        last_good=_snapshot_from_json(f"{context}.last_good", record["last_good"]),
        fetched_at_s=_require_optional_number(context, "fetched_at_s", record["fetched_at_s"]),
        consecutive_failures=_require_int(
            context, "consecutive_failures", record["consecutive_failures"]
        ),
        last_error=_require_optional_str(context, "last_error", record["last_error"]),
        backoff_until_s=_require_optional_number(
            context, "backoff_until_s", record["backoff_until_s"]
        ),
        last_429_at_s=_require_optional_number(context, "last_429_at_s", record["last_429_at_s"]),
        next_poll_at_s=_require_optional_number(
            context, "next_poll_at_s", record["next_poll_at_s"]
        ),
        poll_interval_s=_require_optional_number(
            context, "poll_interval_s", record["poll_interval_s"]
        ),
    )


def _validate_version(version: object) -> None:
    # bool is a subclass of int (True == 1), so a bare int check would let a
    # JSON true pass as schema version 1
    if not isinstance(version, int) or isinstance(version, bool) or version != SCHEMA_VERSION:
        raise ValueError(
            f"usage cache schemaVersion {version!r} is not supported (expected {SCHEMA_VERSION})"
        )


def _accounts_from_document(document: object) -> dict[str, UsageCacheEntry]:
    document_map = _object_map(document, f"usage cache must be a JSON object, got {document!r}")
    _require_keys("usage cache", _DOCUMENT_KEYS, document_map)
    _validate_version(document_map["schemaVersion"])
    accounts_map = _object_map(
        document_map["accounts"],
        f"usage cache accounts must be a JSON object, got {document_map['accounts']!r}",
    )
    return {name: _entry_from_json(name, record) for name, record in accounts_map.items()}


def _document_from_accounts(accounts: dict[str, UsageCacheEntry]) -> dict[str, object]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "accounts": {name: _entry_to_json(entry) for name, entry in accounts.items()},
    }


class FileUsageCache(UsageCachePort):
    """UsageCachePort over a 0600 atomic usage-cache.json (plan §4.3).

    Example:
        cache = FileUsageCache(store_root=Path("~/.local/share/cam"))
        cache.save("work", replace(cache.load("work"), last_good=snapshot))
    """

    def __init__(self, store_root: Path) -> None:
        """Store at *store_root*: usage-cache.json + the shared .lock live there."""
        self._path = store_root / "usage-cache.json"
        self._lock_path = store_root / ".lock"

    def _read(self) -> dict[str, UsageCacheEntry]:
        if not self._path.exists():
            return {}
        return _accounts_from_document(json.loads(self._path.read_bytes()))

    def load(self, account_key: str) -> UsageCacheEntry:
        """The account's cached entry, or EMPTY_USAGE_CACHE_ENTRY when unknown (port contract)."""
        return self._read().get(account_key, EMPTY_USAGE_CACHE_ENTRY)

    def save(self, account_key: str, entry: UsageCacheEntry) -> None:
        """Replace the account's cached entry, under the store's shared lock (port contract)."""
        fsio.ensure_private_dir(self._path.parent)
        with exclusive_file_lock(self._lock_path):
            accounts = self._read()
            accounts[account_key] = entry
            fsio.atomic_write_json(self._path, _document_from_accounts(accounts))
