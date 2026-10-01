"""One coherent pass over registry + live slot + dirs + usage cache.

The TUI polls this instead of calling three use cases and reading the cache
itself: the active marker, quarantine flags, parked-credential state, and
cached usage all come from a single ``execute()``, so a frame never mixes
rows from different instants.
"""

from dataclasses import dataclass

from claude_acc_manager.accounts.application.ports import (
    AccountDirPort,
    AccountStorePort,
    ActiveSlotPort,
)
from claude_acc_manager.accounts.domain.entities import Account
from claude_acc_manager.accounts.domain.oauth_identity import (
    OAuthIdentity,
    oauth_identity_from_config,
)
from claude_acc_manager.accounts.domain.services.identity_match import match_account_by_uuid
from claude_acc_manager.usage.application.ports import ClockPort, UsageCachePort
from claude_acc_manager.usage.domain.usage_cache_entry import UsageCacheEntry


@dataclass(frozen=True)
class AccountView:
    """One row: the registry record plus the flags the UI renders against it.

    ``has_credentials`` is dir-presence — the live account's credential sits
    in the live slot instead (its dir is empty by design), so switching
    needs ``is_active or has_credentials``, not just the flag.
    """

    account: Account
    is_active: bool
    is_quarantined: bool
    has_credentials: bool
    usage: UsageCacheEntry


@dataclass(frozen=True)
class AccountsView:
    """The whole dashboard, taken at one instant.

    ``active_name`` is live-resolved (the uuid in the live config matched
    against the registry), not the registry pointer — the pointer can drift,
    the live config is truth. ``live_identity`` is the parsed login when the
    live slot carries one, managed or not — ``live_identity is not None and
    active_name is None`` names an unmanaged login.
    """

    active_name: str | None
    live_identity: OAuthIdentity | None
    accounts: tuple[AccountView, ...]
    taken_at_s: float


class CollectAccountsView:
    """Assemble an AccountsView from the registry, live slot, dirs, and cache.

    Example:
        view = CollectAccountsView(store, slot, files, cache, clock).execute()
    """

    def __init__(
        self,
        store: AccountStorePort,
        slot: ActiveSlotPort,
        account_files: AccountDirPort,
        cache: UsageCachePort,
        clock: ClockPort,
    ) -> None:
        """Store the injected ports."""
        self._store = store
        self._slot = slot
        self._files = account_files
        self._cache = cache
        self._clock = clock

    def execute(self) -> AccountsView:
        """Return the one-pass view.

        Raises ValueError when the live config's ``oauthAccount`` block is
        present but malformed (same surfacing rule as ``StatusAccount``).
        """
        now_s = self._clock.now_epoch_s()
        accounts = self._store.list_accounts()
        live_identity, active_name = self._live_match(accounts)
        quarantined = {entry.name for entry in self._store.quarantined()}
        rows = tuple(self._row(account, active_name, quarantined) for account in accounts)
        return AccountsView(
            active_name=active_name,
            live_identity=live_identity,
            accounts=rows,
            taken_at_s=now_s,
        )

    def _live_match(self, accounts: list[Account]) -> tuple[OAuthIdentity | None, str | None]:
        """The parsed live identity plus the registry name it maps to."""
        config = self._slot.read_config()
        if config is None:
            return None, None
        identity = oauth_identity_from_config(config)
        if identity is None:
            return None, None
        return identity, match_account_by_uuid(accounts, identity.account_uuid)

    def _row(self, account: Account, active_name: str | None, quarantined: set[str]) -> AccountView:
        """One account's row — flags resolved against the live match."""
        name = account.name.value
        return AccountView(
            account=account,
            is_active=name == active_name,
            is_quarantined=name in quarantined,
            has_credentials=self._files.read_credentials(self._store.account_dir(account.name))
            is not None,
            usage=self._cache.load(name),
        )
