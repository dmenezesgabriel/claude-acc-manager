"""LineageQuarantinePort fake recording tombstoned account names."""

from claude_acc_manager.accounts.application.ports import LineageQuarantinePort
from claude_acc_manager.accounts.domain.entities import QuarantineEntry
from claude_acc_manager.accounts.domain.value_objects import AccountName


class FakeLineageQuarantine(LineageQuarantinePort):
    """Records each tombstoned name; returns the entry it would write."""

    def __init__(self) -> None:
        """Start with no tombstones recorded."""
        self.calls: list[str] = []

    def execute(self, name: AccountName) -> QuarantineEntry:
        """Record *name* and return a permanent_auth_error-shaped entry."""
        self.calls.append(name.value)
        return QuarantineEntry(name.value, "permanent_auth_error", "2026-09-10T12:00:00Z", None)
