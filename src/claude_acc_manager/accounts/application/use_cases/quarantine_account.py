"""Use case for recording an account's dead-lineage tombstone."""

from claude_acc_manager.accounts.application.ports import AccountStorePort, ClockPort
from claude_acc_manager.accounts.domain.entities import QuarantineEntry
from claude_acc_manager.accounts.domain.value_objects import AccountName


class QuarantineAccount:
    """Quarantine an account whose refresh token the provider declared dead.

    The caller (a switch that hit ``invalid_grant``, later the auto-switcher)
    supplies the fingerprint of the credential that failed so the tombstone
    binds one lineage — a re-login under the same name writes a different
    fingerprint and the stale tombstone clears.

    Example:
        quarantine = QuarantineAccount(store, clock)
        entry = quarantine.execute(AccountName("work"),
                                   "permanent_auth_error", "sha256:…")
    """

    def __init__(self, store: AccountStorePort, clock: ClockPort) -> None:
        """Store the injected ports."""
        self._store = store
        self._clock = clock

    def execute(self, name: AccountName, reason: str, fingerprint: str | None) -> QuarantineEntry:
        """Record the tombstone for *name*; ``KeyError`` when unknown."""
        entry = QuarantineEntry(
            name=name.value,
            reason=reason,
            at=self._clock.now_iso(),
            refresh_token_fingerprint=fingerprint,
        )
        self._store.set_quarantined(entry)
        return entry
