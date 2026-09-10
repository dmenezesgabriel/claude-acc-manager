"""Account domain entities."""

from dataclasses import dataclass

from claude_acc_manager.accounts.domain.value_objects import AccountName


@dataclass(frozen=True)
class Account:
    """One registered OAuth subscription account.

    Carries the oauthAccount identity captured at add time (claude-swap
    switcher.py account record) plus the registry bookkeeping: the name is the
    registry key (and the account's directory name under the store), the org
    fields are optional because a fresh login's identity carries none (M0
    empirical probe, 2026-09-10). Holds no filesystem paths — the store owns
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
