"""Shared view/snapshot builders for the TUI renderer tests.

``account_view`` and ``usage_snapshot`` build the domain objects the pure
renderers consume; ``card_plain`` renders the account-card visual to flat
text so assertions can pin the exact shape.
"""

from datetime import UTC, datetime

from textual.visual import Visual

from claude_acc_manager.accounts.application.use_cases.collect_accounts_view import (
    AccountView,
)
from claude_acc_manager.accounts.domain.entities import Account
from claude_acc_manager.tui.theme import CAM_DARK, CAM_LIGHT, Palette
from claude_acc_manager.tui.visuals import AccountCardVisual
from claude_acc_manager.usage.domain.usage_cache_entry import UsageCacheEntry
from claude_acc_manager.usage.domain.usage_snapshot import (
    ScopedWindow,
    UsageSnapshot,
    UsageWindow,
)
from support.rich_asserts import visual_plain
from support.use_cases import make_account

DARK = Palette.from_theme(CAM_DARK)
LIGHT = Palette.from_theme(CAM_LIGHT)
NOW = 1_800_000_000.0


def iso(epoch_s: float) -> str:
    """The ``resets_at`` wire shape for a known epoch."""
    return datetime.fromtimestamp(epoch_s, tz=UTC).isoformat()


def account_view(
    name: str = "work",
    *,
    is_active: bool = False,
    is_quarantined: bool = False,
    enabled: bool = True,
    last_good: UsageSnapshot | None = None,
    fetched_at_s: float | None = NOW,
    last_error: str | None = None,
) -> AccountView:
    """An AccountView with the usage fields the renderers read."""
    account = make_account(name)
    if not enabled:
        account = Account(
            name=account.name,
            email=account.email,
            account_uuid=account.account_uuid,
            organization_uuid=account.organization_uuid,
            organization_name=account.organization_name,
            added_at=account.added_at,
            enabled=False,
        )
    return AccountView(
        account=account,
        is_active=is_active,
        is_quarantined=is_quarantined,
        has_credentials=True,
        usage=UsageCacheEntry(
            last_good=last_good,
            fetched_at_s=fetched_at_s,
            consecutive_failures=0,
            last_error=last_error,
            backoff_until_s=None,
            last_429_at_s=None,
            next_poll_at_s=None,
            poll_interval_s=None,
        ),
    )


def usage_snapshot(
    five_hour: float | None = 47.0,
    seven_day: float | None = 63.0,
    scoped: tuple[ScopedWindow, ...] = (),
) -> UsageSnapshot:
    """A snapshot with the standard two windows, scoped extras optional."""
    return UsageSnapshot(
        five_hour=None
        if five_hour is None
        else UsageWindow(pct=five_hour, resets_at=iso(NOW + 7980)),
        seven_day=None
        if seven_day is None
        else UsageWindow(pct=seven_day, resets_at=iso(NOW + 500_000)),
        scoped=scoped,
    )


def card_plain(
    view: AccountView, width: int = 80, *, redact: bool = False, threshold: float | None = None
) -> tuple[Visual, str]:
    """The card visual plus its flat render — the ``account_card_text`` pair."""
    visual = AccountCardVisual(
        view, width, threshold=threshold, now=NOW, palette=DARK, redact=redact
    )
    return visual, visual_plain(visual, 400)
