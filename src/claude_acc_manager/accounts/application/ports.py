"""Ports of the accounts component — the single map of every boundary."""

from pathlib import Path
from typing import Protocol, runtime_checkable

from claude_acc_manager.accounts.domain.entities import Account
from claude_acc_manager.accounts.domain.value_objects import AccountName


@runtime_checkable
class AccountStorePort(Protocol):
    """Persistence boundary for registered accounts.

    Implementations guarantee private modes and atomic writes (plan §5.3).
    The registry order is the rotation order; the active pointer names the
    account whose credentials currently sit in the live slot.

    Example:
        store.upsert(account)
        store.set_active(AccountName("work"))
    """

    def upsert(self, account: Account) -> None:
        """Insert or update *account*, appending to the order if new."""
        ...

    def remove(self, name: AccountName) -> None:
        """Drop the account, its order entry, and an active pointer to it."""
        ...

    def get(self, name: AccountName) -> Account | None:
        """Return the account or None when unknown."""
        ...

    def list_accounts(self) -> list[Account]:
        """All accounts in registry order."""
        ...

    def set_enabled(self, name: AccountName, enabled: bool) -> None:
        """Toggle the account's enabled flag."""
        ...

    def set_active(self, name: AccountName | None) -> None:
        """Point the registry's active pointer at *name* (or unset it)."""
        ...

    def active(self) -> Account | None:
        """The active account, or None when unset or dangling."""
        ...


@runtime_checkable
class ActiveSlotPort(Protocol):
    """Boundary for reading/writing Claude Code's live credential + config slot.

    The active slot is the default ``CLAUDE_CONFIG_DIR`` that plain ``claude``
    reads from: ``~/.claude/.credentials.json`` for OAuth tokens and
    ``~/.claude.json`` for the ``oauthAccount`` identity marker.

    Example:
        slot = ActiveSlotAdapter(env={}, home=Path.home())
        creds = slot.read_credentials()
    """

    def read_credentials(self) -> dict[str, object] | None:
        """Parse ``.credentials.json``; ``None`` when absent.

        Raises ValueError when the file exists but is torn or not a JSON object.
        """
        ...

    def write_credentials(self, credentials: dict[str, object]) -> None:
        """Atomically replace ``.credentials.json`` with mode 0600."""
        ...

    def read_config(self) -> dict[str, object] | None:
        """Parse ``~/.claude.json``; ``None`` when absent.

        Raises ValueError when the file exists but is torn or not a JSON object.
        """
        ...

    def write_config(self, config: dict[str, object]) -> None:
        """Atomically replace ``~/.claude.json`` with mode 0600."""
        ...

    def splice_config_oauth_account(self, oauth_account: dict[str, object]) -> None:
        """Read config → set only ``oauthAccount`` key → write back.

        When the config is torn, salvages it aside first then writes a fresh
        config containing only the ``oauthAccount`` key.
        """
        ...

    def salvage_torn_config(self) -> Path | None:
        """Copy a torn config aside before it is overwritten.

        Returns the salvage path, or ``None`` when the file is absent.
        Raises OSError when the salvage copy fails.
        """
        ...
