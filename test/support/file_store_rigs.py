"""Shared builders for the ``FileAccountStore`` tests.

``make_store`` points the real adapter at an injected root; the ``registry_*``
helpers read/write the on-disk document so validation tests can pin both the
schema and the exact failure messages.
"""

import json
from pathlib import Path

from claude_acc_manager.accounts.domain.entities import Account, QuarantineEntry
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.accounts.infrastructure.file_account_store import (
    FileAccountStore,
)


def make_account(name: str = "work", **overrides: object) -> Account:
    """An account row with the registry's full field shape.

    Example:
        >>> make_account("home", enabled=False).name
        AccountName('home')
    """
    fields: dict[str, object] = {
        "email": "user@example.com",
        "account_uuid": "acc-uuid-1",
        "organization_uuid": "org-uuid-1",
        "organization_name": "ExampleOrg",
        "added_at": "2026-09-10T12:00:00Z",
    }
    fields.update(overrides)
    return Account(AccountName(name), **fields)  # type: ignore[arg-type]


def quarantine_entry(name: str = "work", **overrides: object) -> QuarantineEntry:
    """A quarantine row for *name*."""
    fields: dict[str, object] = {
        "name": name,
        "reason": "permanent_auth_error",
        "at": "2026-09-10T12:00:00Z",
        "refresh_token_fingerprint": "sha256:dead",
    }
    fields.update(overrides)
    return QuarantineEntry(**fields)  # type: ignore[arg-type]


def make_store(tmp_path: Path) -> FileAccountStore:
    """The real adapter rooted at a tmp dir."""
    return FileAccountStore(store_root=tmp_path / "store")


def registry_doc(store_root: Path) -> dict[str, object]:
    """Read back the on-disk ``registry.json``."""
    text = (store_root / "registry.json").read_text(encoding="utf-8")
    return json.loads(text)  # type: ignore[no-any-return]


def write_registry(store_root: Path, document: dict[str, object]) -> None:
    """Write a ``registry.json`` document directly."""
    store_root.mkdir(parents=True, exist_ok=True)
    (store_root / "registry.json").write_text(json.dumps(document), encoding="utf-8")
