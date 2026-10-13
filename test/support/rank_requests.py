"""Shared builders for the ``auto_rank`` domain-service tests.

``rank_request`` fills a ``RankingRequest`` with defaults so a test names only
the fields it varies; ``snap`` builds a ``UsageSnapshot`` from window pcts and
reset epochs.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from claude_acc_manager.accounts.domain.services.switch_selection import HeadroomMap
from claude_acc_manager.auto.domain.services.auto_rank import (
    RankingRequest,
    Trigger,
)
from claude_acc_manager.settings.domain.settings_spec import AutoStrategy
from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot, UsageWindow

NOW_S = 1_700_000_000.0


def rank_iso(epoch_s: float) -> str:
    """Format an epoch second the way snapshots carry resets."""
    return datetime.fromtimestamp(epoch_s, tz=UTC).isoformat()


def snap(
    five_pct: float | None = None,
    five_reset_s: float | None = None,
    seven_pct: float | None = None,
    seven_reset_s: float | None = None,
) -> UsageSnapshot:
    """A snapshot from window pct + reset epoch seconds (None window = absent)."""
    five = (
        UsageWindow(pct=five_pct, resets_at=rank_iso(five_reset_s) if five_reset_s else None)
        if five_pct is not None
        else None
    )
    seven = (
        UsageWindow(pct=seven_pct, resets_at=rank_iso(seven_reset_s) if seven_reset_s else None)
        if seven_pct is not None
        else None
    )
    return UsageSnapshot(five_hour=five, seven_day=seven, scoped=())


def rank_request(
    *,
    trigger: Trigger = "proactive",
    candidates: Sequence[str] = ("a", "b"),
    snapshots: Mapping[str, UsageSnapshot | None] | None = None,
    headroom: HeadroomMap | None = None,
    active: str = "c",
    active_headroom: float | None = None,
    threshold: float = 90.0,
    hysteresis_pct: float = 10.0,
    strategy: AutoStrategy = "best",
    now_s: float = NOW_S,
) -> RankingRequest:
    """A RankingRequest; defaults fill the fields a given call doesn't vary."""
    return RankingRequest(
        trigger=trigger,
        candidates=candidates,
        snapshots={} if snapshots is None else snapshots,
        headroom={} if headroom is None else headroom,
        active=active,
        active_headroom=active_headroom,
        threshold=threshold,
        hysteresis_pct=hysteresis_pct,
        strategy=strategy,
        now_s=now_s,
    )
