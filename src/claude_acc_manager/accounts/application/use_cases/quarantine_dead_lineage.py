"""Tombstone the refresh-token lineage the provider permanently rejected.

``invalid_grant`` at refresh means the lineage is dead, not rate-limited
(ADR-0009). The tombstone is bound by the *parked* credential's
refresh-token fingerprint — the use case reads the account dir itself, so
callers that only learned "the provider said no" don't need to know where
the file lives. A re-login under the same name parks a different
fingerprint and the stale tombstone clears.
"""

from claude_acc_manager.accounts.application.ports import (
    AccountDirPort,
    AccountStorePort,
    ClockPort,
    LineageQuarantinePort,
)
from claude_acc_manager.accounts.domain.credential_fields import refresh_token_fingerprint
from claude_acc_manager.accounts.domain.entities import QuarantineEntry
from claude_acc_manager.accounts.domain.value_objects import AccountName


class QuarantineDeadLineage(LineageQuarantinePort):
    """Record a ``permanent_auth_error`` tombstone for *name*'s lineage.

    Example:
        entry = QuarantineDeadLineage(store, files, clock).execute(AccountName("work"))
    """

    def __init__(
        self, store: AccountStorePort, account_files: AccountDirPort, clock: ClockPort
    ) -> None:
        """Store the injected ports."""
        self._store = store
        self._files = account_files
        self._clock = clock

    def execute(self, name: AccountName) -> QuarantineEntry:
        """Tombstone *name*'s dead lineage; ``KeyError`` when unregistered."""
        parked = self._files.read_credentials(self._store.account_dir(name))
        fingerprint = refresh_token_fingerprint(parked) if parked is not None else None
        entry = QuarantineEntry(
            name.value, "permanent_auth_error", self._clock.now_iso(), fingerprint
        )
        self._store.set_quarantined(entry)
        return entry
