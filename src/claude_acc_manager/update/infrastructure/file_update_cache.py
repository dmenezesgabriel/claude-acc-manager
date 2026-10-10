"""update-check.json persistence for the release-check cache (§3).

Schema v1 (this tool's own file, not a mirror of the index's wire shape):
{"schemaVersion": 1, "checked_at_s": <epoch seconds>, "latest_version":
<str|null>}. One record per file — the check has a single global cadence,
unlike the per-account usage cache. Drift (unknown/missing fields, wrong
types, wrong version) fails loudly (§8), same discipline as
usage/infrastructure/file_usage_cache.py. Mutations run under the store's
shared .lock; an absent file means no check has ever run, so ``load``
returns None — never confuse it with a cached failure (a real record
whose latest_version is null).
"""

from collections.abc import Mapping
from pathlib import Path

from claude_acc_manager.shared import fsio
from claude_acc_manager.shared.file_lock import exclusive_file_lock
from claude_acc_manager.update.application.ports import (
    UpdateCheckCachePort,
    UpdateCheckRecord,
)

SCHEMA_VERSION = 1

_DOCUMENT_KEYS = ("schemaVersion", "checked_at_s", "latest_version")


def _require_keys(context: str, keys: tuple[str, ...], record: Mapping[str, object]) -> None:
    unknown = [key for key in record if key not in keys]
    if unknown:
        raise ValueError(f"{context} has unknown fields {unknown}")
    missing = [key for key in keys if key not in record]
    if missing:
        raise ValueError(f"{context} is missing fields {missing}")


def _require_number(context: str, key: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context}: {key} must be a number, got {value!r}")
    return float(value)


def _require_optional_str(context: str, key: str, value: object) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{context}: {key} must be a str or null, got {value!r}")
    return value


def _validate_version(version: object) -> None:
    # bool is a subclass of int (True == 1), so a bare int check would let a
    # JSON true pass as schema version 1
    if not isinstance(version, int) or isinstance(version, bool) or version != SCHEMA_VERSION:
        raise ValueError(
            f"update-check schemaVersion {version!r} is not supported (expected {SCHEMA_VERSION})"
        )


def _record_from_document(document: Mapping[str, object]) -> UpdateCheckRecord:
    context = "update-check"
    _require_keys(context, _DOCUMENT_KEYS, document)
    _validate_version(document["schemaVersion"])
    return UpdateCheckRecord(
        checked_at_s=_require_number(context, "checked_at_s", document["checked_at_s"]),
        latest_version=_require_optional_str(context, "latest_version", document["latest_version"]),
    )


def _document_from_record(record: UpdateCheckRecord) -> dict[str, object]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "checked_at_s": record.checked_at_s,
        "latest_version": record.latest_version,
    }


class FileUpdateCheckCache(UpdateCheckCachePort):
    """UpdateCheckCachePort over a 0600 atomic update-check.json (§3).

    Example:
        cache = FileUpdateCheckCache(store_root=Path("~/.local/share/cam"))
        cache.save(UpdateCheckRecord(checked_at_s=now, latest_version="1.2.0"))
    """

    def __init__(self, store_root: Path) -> None:
        """Store at *store_root*: update-check.json + the shared .lock live there."""
        self._path = store_root / "update-check.json"
        self._lock_path = store_root / ".lock"

    def load(self) -> UpdateCheckRecord | None:
        """The last check record, or None when no check has ever run (port contract)."""
        if not self._path.exists():
            return None
        return _record_from_document(fsio.read_json_object(self._path, "update-check"))

    def save(self, record: UpdateCheckRecord) -> None:
        """Replace the last-check record, under the store's shared lock (port contract)."""
        fsio.ensure_private_dir(self._path.parent)
        with exclusive_file_lock(self._lock_path):
            fsio.atomic_write_json(self._path, _document_from_record(record))
