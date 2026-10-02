"""Report which account Claude Code's live slot is using, and if it's managed."""

from claude_acc_manager.accounts.application.ports import (
    AccountStorePort,
    ActiveAccountStatus,
    ActiveSlotPort,
)
from claude_acc_manager.accounts.domain.oauth_identity import oauth_identity_from_config
from claude_acc_manager.accounts.domain.services.identity_match import match_account_by_uuid


class StatusAccount:
    """Read the live ``oauthAccount`` identity and classify it against the store.

    Returns ``None`` when no account is logged in. Matching is by
    ``accountUuid`` — the same account can appear under different UUIDs across
    orgs, and the UUID is the unambiguous key (claude-swap switcher.py
    identity handling).

    Example:
        StatusAccount(active_slot, store).execute()
    """

    def __init__(self, active_slot: ActiveSlotPort, store: AccountStorePort) -> None:
        """Store the injected ports."""
        self._active_slot = active_slot
        self._store = store

    def execute(self) -> ActiveAccountStatus | None:
        """Return the live slot's status, or ``None`` when nothing is logged in.

        Raises ValueError when the config's ``oauthAccount`` block is present
        but malformed (surfaced, not swallowed — docs/architecture.md §8).
        """
        config = self._active_slot.read_config()
        if config is None:
            return None
        identity = oauth_identity_from_config(config)
        if identity is None:
            return None

        managed_as = match_account_by_uuid(self._store.list_accounts(), identity.account_uuid)
        return ActiveAccountStatus(
            email=identity.email,
            account_uuid=identity.account_uuid,
            organization_uuid=identity.organization_uuid,
            organization_name=identity.organization_name,
            managed_as=managed_as,
        )
