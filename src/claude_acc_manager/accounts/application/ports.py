"""Ports of the accounts component — the single map of every boundary."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NamedTuple, Protocol, runtime_checkable

from claude_acc_manager.accounts.domain.entities import Account, QuarantineEntry
from claude_acc_manager.accounts.domain.services.switch_selection import SkippedCandidate
from claude_acc_manager.accounts.domain.value_objects import AccountName


@runtime_checkable
class AccountStorePort(Protocol):
    """Persistence boundary for registered accounts.

    Implementations guarantee private modes and atomic writes (docs/architecture.md §8).
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

    def quarantined(self) -> list[QuarantineEntry]:
        """Every dead-lineage tombstone, in record order."""
        ...

    def set_quarantined(self, entry: QuarantineEntry) -> None:
        """Record (or replace) the tombstone for *entry.name*.

        Quarantine names a registered lineage — KeyError when no account
        with that name exists (same contract as set_enabled).
        """
        ...

    def clear_quarantined(self, name: AccountName) -> None:
        """Drop *name*'s tombstone; no-op when it has none."""
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
        lands at add time (docs/architecture.md §3): ``<store_root>/accounts/<name>/``.
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

    def credentials_path(self) -> Path:
        """Return the resolved live credentials path.

        The switch's scoped-shell guard compares this against each registered
        ``accounts/<name>/`` dir — under ``CLAUDE_CONFIG_DIR`` it points inside
        one of them, which means "the live slot" is a scoped profile, not the
        real default claude slot.
        """
        ...

    def read_credentials(self) -> dict[str, object] | None:
        """Parse ``.credentials.json``; ``None`` when absent.

        Raises ValueError when the file exists but is torn or not a JSON object.
        """
        ...

    def write_credentials(self, credentials: dict[str, object]) -> None:
        """Atomically replace ``.credentials.json`` with mode 0600."""
        ...

    def delete_credentials(self) -> None:
        """Remove ``.credentials.json`` when present; no-op when absent.

        Rollback restores "no credential file" with this — the undo of
        ``write_credentials`` when the slot was empty before the switch.
        """
        ...

    def read_config(self) -> dict[str, object] | None:
        """Parse ``~/.claude.json``; ``None`` when absent.

        Raises ValueError when the file exists but is torn or not a JSON object.
        """
        ...

    def write_config(self, config: dict[str, object]) -> None:
        """Atomically replace ``~/.claude.json`` with mode 0600."""
        ...

    def delete_config(self) -> None:
        """Remove the resolved global config when present; no-op when absent."""
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
    are never copied at add time (ADR-0009). Ambient credential env is
    stripped so claude can't skip its login prompt.

    Example:
        launcher = ClaudeLoginLauncher()
        ok = launcher.launch(Path("~/.local/share/cam/accounts/work"))
    """

    def launch(self, account_dir: Path) -> bool:
        """Run ``claude`` with CLAUDE_CONFIG_DIR=*account_dir*.

        Returns True when the interactive login exits 0; False when claude
        is missing or exits non-zero.
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
class AccountDirPort(Protocol):
    """Boundary for one account's credential + config files in its own dir.

    Under the switch's move model the account dir relinquishes
    ``.credentials.json`` while its account is live — the live slot holds the
    only copy of the rotating refresh token — so reads legitimately return
    ``None`` (absent is a state, not an error; tears still raise).

    Example:
        creds = files.read_credentials(store.account_dir(AccountName("work")))
    """

    def read_credentials(self, account_dir: Path) -> dict[str, object] | None:
        """Parse ``<account_dir>/.credentials.json``; ``None`` when absent."""
        ...

    def write_credentials(self, account_dir: Path, credentials: dict[str, object]) -> None:
        """Atomically write the credential into *account_dir* with mode 0600."""
        ...

    def delete_credentials(self, account_dir: Path) -> None:
        """Remove the account's credential file; no-op when absent."""
        ...

    def read_config(self, account_dir: Path) -> dict[str, object] | None:
        """Parse the account's global config (legacy reroute); ``None`` when absent."""
        ...

    def write_config(self, account_dir: Path, config: dict[str, object]) -> None:
        """Atomically write the account's config with mode 0600."""
        ...

    def delete_config(self, account_dir: Path) -> None:
        """Remove the account's config file; no-op when absent."""
        ...


@runtime_checkable
class UnclaimedCredentialPort(Protocol):
    """Boundary for preserving a live credential that matches no account.

    When the outgoing live login belongs to no registered account (a pre-cam
    manual login, a work account managed elsewhere), the switch stashes its
    bytes under ``<store>/unclaimed/`` instead of destroying them.

    Example:
        preserved = unclaimed.preserve(creds, config, "foreign")
    """

    def preserve(
        self,
        credentials: dict[str, object],
        config: dict[str, object] | None,
        reason: str,
    ) -> Path:
        """Write the pair under ``unclaimed/``; return the credential path."""
        ...


@runtime_checkable
class ClaudeLockPort(Protocol):
    """Boundary for coordinating swaps with claude-code's mkdir locks.

    Claude-code guards its credentials and global config with mkdir-based
    locks: creating the directory acquires, removing it releases, and its
    mtime is the liveness heartbeat (the proper-lockfile protocol its bundle
    ships — observed in 2.1.218). Swaps must hold the same locks so the
    write never races a live process.

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


@runtime_checkable
class ClockPort(Protocol):
    """Boundary for time operations, enabling testable timestamp generation.

    Example:
        timestamp = clock.now_iso()
    """

    def now_iso(self) -> str:
        r"""Return current UTC timestamp as ISO-8601 string (e.g. "2026-09-10T12:00:00Z")."""
        ...


SwitchStatus = Literal[
    "switched",
    "already-active",
    "no-valid-target",
    "already-best",
    "candidates-exhausted",
    "usage-unavailable",
]
"""Outcome vocabulary shared by ``SwitchAccount`` and its port consumers."""


@dataclass(frozen=True)
class SwitchResult:
    """What a switch did or would do — transports render this verbatim.

    Lives with the ports (like ``RefreshedTokens`` in usage) so
    ``SwitchExecutorPort`` can name it without importing the use case —
    the use case already imports this module.
    """

    outcome: SwitchStatus
    target: str | None = None
    previous: str | None = None
    unmanaged_live: bool = False
    preserved_to: Path | None = None
    quarantined: tuple[str, ...] = ()
    skipped: tuple[SkippedCandidate, ...] = ()
    dry_run: bool = False


class SwitchExecutorPort(Protocol):
    """The engine-facing seam for the switch transaction.

    ``SwitchAccount`` satisfies it structurally — the port exists so the
    auto engine depends on the capability, not the use-case class (AGENTS:
    a use case never depends on another use case).

    Example:
        result = switch_executor.execute(AccountName("work"), dry_run=False)
    """

    def execute(self, target: AccountName, *, dry_run: bool) -> SwitchResult:
        """Move *target*'s credential into the live slot, atomically."""
        ...


class ActiveAccountStatus(NamedTuple):
    """The live slot's identity plus the registry name it maps to, if any.

    ``managed_as`` is the account name when the live ``accountUuid`` matches
    a registered account, else ``None`` (a login this tool does not manage).
    """

    email: str
    account_uuid: str
    organization_uuid: str | None
    organization_name: str | None
    managed_as: str | None


class ActiveIdentityPort(Protocol):
    """The engine-facing seam for live-slot identity resolution.

    ``StatusAccount`` satisfies it structurally. The engine must not act on
    the registry's active pointer alone — an unmanaged live login would be
    overwritten without a backup.

    Example:
        status = active_identity.execute()  # None when logged out
    """

    def execute(self) -> ActiveAccountStatus | None:
        """The live slot's status, or ``None`` when nothing is logged in."""
        ...


class LineageQuarantinePort(Protocol):
    """The engine-facing seam for tombstoning a dead credential lineage.

    ``QuarantineDeadLineage`` satisfies it structurally — the tombstone is
    fingerprint-bound so a later re-login releases it automatically
    (ADR-0009).

    Example:
        quarantine.execute(AccountName("work"))
    """

    def execute(self, name: AccountName) -> QuarantineEntry:
        """Record a ``permanent_auth_error`` tombstone for *name*'s lineage."""
        ...
