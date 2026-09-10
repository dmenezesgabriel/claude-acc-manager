"""Ports of the accounts component — the single map of every boundary."""

from contextlib import AbstractContextManager
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

    def account_dir(self, name: AccountName) -> Path:
        """Return the account's isolated CLAUDE_CONFIG_DIR under the store.

        Each registered account owns a real config directory where its login
        lands at add time (plan §4.3): ``<store_root>/accounts/<name>/``.
        """
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


@runtime_checkable
class LoginLauncherPort(Protocol):
    """Boundary for launching an interactive claude login in an isolated dir.

    The login lands directly in the account's own CLAUDE_CONFIG_DIR — tokens
    are never copied at add time (plan §4.4, ai-usagebar account.rs add).
    Ambient credential env is stripped so claude can't skip its login prompt.

    Example:
        launcher = ClaudeLoginLauncher()
        ok = launcher.launch(Path("~/.local/share/cam/accounts/work"))
    """

    def launch(self, account_dir: Path) -> bool:
        """Run ``claude`` with CLAUDE_CONFIG_DIR=*account_dir*.

        Returns True when the interactive login exits 0 (ai-usagebar's
        success signal); False when claude is missing or exits non-zero.
        """
        ...


@runtime_checkable
class AccountDirReaderPort(Protocol):
    """Boundary for reading a captured login from an account's own directory.

    After ``claude`` writes its login into the account's CLAUDE_CONFIG_DIR,
    this reads the OAuth credential and the ``oauthAccount`` identity marker
    back so the account can be registered.

    Example:
        creds, config = reader.read_account_data(Path(".../accounts/work"))
    """

    def read_account_data(self, account_dir: Path) -> tuple[dict[str, object], dict[str, object]]:
        """Return (credentials, config) parsed from *account_dir*.

        Raises ValueError when either file is absent or torn — a login that
        produced no credential must surface as a failure, not a silent skip.
        """
        ...


@runtime_checkable
class ClaudeLockPort(Protocol):
    """Boundary for coordinating swaps with claude-code's mkdir locks.

    Claude-code guards its credentials and global config with mkdir-based
    locks: creating the directory acquires, removing it releases, and its
    mtime is the liveness heartbeat (claude-swap claude_locks.py wrapping
    the proper-lockfile protocol bundled in claude-code 2.1.218). Swaps must
    hold the same locks so the write never races a live process.

    Example:
        with locks.credentials_locked(timeout_s=5.0):
            slot.write_credentials(fresh_credentials)
    """

    def credentials_locked(self, *, timeout_s: float | None = None) -> AbstractContextManager[None]:
        """Hold the primary and legacy credential locks for the duration.

        Raises TimeoutError when a live holder (often claude-code itself)
        keeps either lock past *timeout_s*.
        """
        ...

    def config_locked(self, *, timeout_s: float | None = None) -> AbstractContextManager[None]:
        """Hold the global-config lock for the duration.

        Raises TimeoutError when a live holder keeps the lock past *timeout_s*.
        """
        ...
