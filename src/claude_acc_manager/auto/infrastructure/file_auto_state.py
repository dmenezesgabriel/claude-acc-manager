"""FileAutoState — AutoStatePort over an atomic 0600 ``auto-state.json``.

Machine-written, never user-edited: a torn file raises loudly (the
docs/architecture.md "tears surface" rule) instead of degrading to an
empty state that would let two engines double-switch. The dedicated
``.auto-state.lock`` serializes the decide→switch→record hold; the store's
shared ``.lock`` is never taken (the switch path takes it — self-deadlock).

Example:
    state = FileAutoState(store_root)
    with state.locked():
        if not in_cooldown(state.load(), now, cooldown_s):
            ...switch...
            state.save(...)
"""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from claude_acc_manager.auto.application.ports import AutoStatePort
from claude_acc_manager.auto.domain.auto_state import EMPTY_AUTO_STATE, AutoState
from claude_acc_manager.shared import fsio
from claude_acc_manager.shared.file_lock import exclusive_file_lock

_SCHEMA_VERSION = 1


def _num_or_none(value: object) -> float | None:
    """*value* as float when it is one, else None (degraded field, not torn file)."""
    return float(value) if isinstance(value, int | float) else None


def _str_or_none(value: object) -> str | None:
    """*value* when it is a string, else None."""
    return value if isinstance(value, str) else None


class FileAutoState(AutoStatePort):
    """AutoStatePort over ``auto-state.json`` + ``.auto-state.lock``."""

    def __init__(self, store_root: Path) -> None:
        """State file and its dedicated lock live directly under *store_root*."""
        self._path = store_root / "auto-state.json"
        self._lock_path = store_root / ".auto-state.lock"

    def load(self) -> AutoState:
        """The persisted state; EMPTY when absent, ValueError when torn."""
        if not self._path.exists():
            return EMPTY_AUTO_STATE
        document = fsio.read_json_object(self._path, "auto-state")
        return AutoState(
            last_switch_at_s=_num_or_none(document.get("lastSwitchAt")),
            last_switch_from=_str_or_none(document.get("lastSwitchFrom")),
            left_headroom=_num_or_none(document.get("leftHeadroom")),
            left_recovery_at_s=_num_or_none(document.get("leftRecoveryAt")),
        )

    @contextmanager
    def locked(self) -> Generator[None]:
        """Exclusive hold on ``.auto-state.lock`` (port contract)."""
        fsio.ensure_private_dir(self._path.parent)
        with exclusive_file_lock(self._lock_path):
            yield

    def save(self, state: AutoState) -> None:
        """Atomically write *state*; the caller must hold ``locked()``."""
        fsio.atomic_write_json(
            self._path,
            {
                "schemaVersion": _SCHEMA_VERSION,
                "lastSwitchAt": state.last_switch_at_s,
                "lastSwitchFrom": state.last_switch_from,
                "leftHeadroom": state.left_headroom,
                "leftRecoveryAt": state.left_recovery_at_s,
            },
        )
