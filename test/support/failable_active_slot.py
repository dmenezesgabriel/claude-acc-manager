"""FakeActiveSlot that records mutations and can be armed to fail one.

Rollback tests need a slot whose ``write_credentials`` (or splice, or delete)
raises at a chosen step — ``arm("write_credentials", boom)`` makes the next
call raise while still recording the attempt in ``calls``.
"""

from pathlib import Path

from support.fake_active_slot import FakeActiveSlot


class FailableActiveSlot(FakeActiveSlot):
    """FakeActiveSlot with per-operation failure injection."""

    def __init__(
        self,
        *,
        credentials: dict[str, object] | None = None,
        config: dict[str, object] | None = None,
        live_credentials_path: Path | None = None,
    ) -> None:
        """Seed the slot like the base fake; start unarmed."""
        super().__init__(
            credentials=credentials,
            config=config,
            live_credentials_path=live_credentials_path,
        )
        self.calls: list[str] = []
        self._armed: dict[str, Exception] = {}
        self._pinned: dict[str, Exception] = {}

    def arm(self, op: str, error: Exception) -> None:
        """The next call to *op* is recorded, then raises *error*."""
        self._armed[op] = error

    def pin(self, op: str, error: Exception) -> None:
        """Every call to *op* raises *error* — including a rollback restore."""
        self._pinned[op] = error

    def _attempt(self, op: str) -> None:
        """Record the attempted call, then raise when armed or pinned."""
        self.calls.append(op)
        if op in self._armed:
            raise self._armed.pop(op)
        if op in self._pinned:
            raise self._pinned[op]

    def write_credentials(self, credentials: dict[str, object]) -> None:
        """Record, maybe raise, else delegate."""
        self._attempt("write_credentials")
        super().write_credentials(credentials)

    def delete_credentials(self) -> None:
        """Record, maybe raise, else delegate."""
        self._attempt("delete_credentials")
        super().delete_credentials()

    def write_config(self, config: dict[str, object]) -> None:
        """Record, maybe raise, else delegate."""
        self._attempt("write_config")
        super().write_config(config)

    def delete_config(self) -> None:
        """Record, maybe raise, else delegate."""
        self._attempt("delete_config")
        super().delete_config()

    def splice_config_oauth_account(self, oauth_account: dict[str, object]) -> None:
        """Record, maybe raise, else delegate."""
        self._attempt("splice_config_oauth_account")
        super().splice_config_oauth_account(oauth_account)
