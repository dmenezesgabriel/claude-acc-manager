"""Match a live OAuth identity to the registry by ``accountUuid``.

The account UUID is the unambiguous key — the same account can appear under
different emails across orgs, and the registry pointer alone can drift from
which credential actually sits in the live slot (docs/architecture.md §3).

Example:
    match_account_by_uuid(store.list_accounts(), identity.account_uuid)
"""

from collections.abc import Iterable

from claude_acc_manager.accounts.domain.entities import Account


def match_account_by_uuid(accounts: Iterable[Account], account_uuid: str) -> str | None:
    """The registry name owning *account_uuid*, in registry order, or None.

    Example:
        match_account_by_uuid(accounts, "acc-uuid") == "work"
    """
    return next(
        (account.name.value for account in accounts if account.account_uuid == account_uuid),
        None,
    )
