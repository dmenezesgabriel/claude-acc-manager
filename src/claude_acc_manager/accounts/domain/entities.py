"""Account domain entities."""

from dataclasses import dataclass

from claude_acc_manager.accounts.domain.value_objects import AccountName


@dataclass(frozen=True)
class Account:
    """One registered OAuth subscription account.

    Carries the oauthAccount identity captured at add time plus the registry
    bookkeeping: the name is the registry key (and the account's directory
    name under the store), the org fields are optional because a fresh
    login's identity carries none. Holds no filesystem paths — the store owns
    the layout (accounts/<name>/ derives from the key).

    Example:
        Account(AccountName("work"), email="user@example.com",
                account_uuid="acc-uuid", organization_uuid=None,
                organization_name=None, added_at="2026-09-10T12:00:00Z")
    """

    name: AccountName
    email: str
    account_uuid: str
    organization_uuid: str | None
    organization_name: str | None
    added_at: str
    enabled: bool = True


@dataclass(frozen=True)
class QuarantineEntry:
    """A tombstone for one account's dead refresh-token lineage.

    Recorded when the provider answers ``invalid_grant`` (a permanent auth
    error — the lineage is dead, not rate-limited). Quarantined accounts are
    excluded from automatic switch picks; an explicit ``cam switch <name>``
    still reaches them. The entry binds the dead lineage by
    ``refresh_token_fingerprint``: when the stored credential's fingerprint
    changes (a successful re-login or rotation), the tombstone is stale —
    it is cleared.

    Example:
        QuarantineEntry("work", "permanent_auth_error",
                        "2026-09-10T12:00:00Z", "sha256:abc…")
    """

    name: str
    reason: str
    at: str
    refresh_token_fingerprint: str | None
