"""Shared builders for the ``poll_policy`` domain-service tests.

``plan`` wraps ``plan_after_fetch`` with the full default argument set so a
test names only the factors it varies; ``poll_snapshot`` and ``cache_entry``
build the domain records the scheduler consumes.
"""

from dataclasses import replace

from claude_acc_manager.usage.domain.services import poll_policy
from claude_acc_manager.usage.domain.usage_cache_entry import (
    EMPTY_USAGE_CACHE_ENTRY,
    UsageCacheEntry,
)
from claude_acc_manager.usage.domain.usage_snapshot import (
    ScopedWindow,
    UsageSnapshot,
    UsageWindow,
)

NOW = 1_000_000.0
HALF = lambda: 0.5  # noqa: E731 — rng midpoint: jitter factor exactly 1.0


def plan(**overrides: object) -> tuple[float, float]:
    """Call ``plan_after_fetch`` with defaults; *overrides* names the deltas."""
    kwargs: dict[str, object] = {
        "prev_interval_s": None,
        "prev_pct": None,
        "new_pct": 10.0,
        "is_active": False,
        "headroom": None,
        "limiting_reset_s": None,
        "earliest_reset_s": None,
        "recent_429": False,
        "threshold": 90.0,
        "now_s": NOW,
        "rng": HALF,
    }
    kwargs.update(overrides)
    return poll_policy.plan_after_fetch(**kwargs)  # type: ignore[arg-type]


def poll_snapshot(
    five_hour: float | None = None,
    seven_day: float | None = None,
    scoped: tuple[ScopedWindow, ...] = (),
) -> UsageSnapshot:
    """A usage snapshot with unset windows left out."""
    return UsageSnapshot(
        five_hour=None if five_hour is None else UsageWindow(pct=five_hour, resets_at=None),
        seven_day=None if seven_day is None else UsageWindow(pct=seven_day, resets_at=None),
        scoped=scoped,
    )


def cache_entry(**kw: object) -> UsageCacheEntry:
    """A cache entry: ``EMPTY_USAGE_CACHE_ENTRY`` with *kw* fields replaced."""
    return replace(EMPTY_USAGE_CACHE_ENTRY, **kw)  # type: ignore[arg-type]
