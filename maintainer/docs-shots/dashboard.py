"""Docs screenshot source: the ``cam tui`` dashboard over the named fakes.

``textual._doc.format_svg`` (the custom fence registered in mkdocs.yml)
runs this module with ``runpy`` and drives the bound ``app`` headless —
the same mechanism textual's own docs use for their rendered fences. The
fakes come from test/support so a docs build needs no claude install,
no network, and renders deterministically.
"""

import sys
from dataclasses import replace
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "test"))

from support.in_memory_usage_cache import InMemoryUsageCache  # noqa: E402
from support.tui_app import wired_app  # noqa: E402

from claude_acc_manager.usage.domain.usage_cache_entry import (  # noqa: E402
    EMPTY_USAGE_CACHE_ENTRY,
    UsageCacheEntry,
)
from claude_acc_manager.usage.domain.usage_snapshot import (  # noqa: E402
    ScopedWindow,
    UsageSnapshot,
    UsageWindow,
)


def _cached(
    five_hour: float,
    seven_day: float,
    scoped: tuple[ScopedWindow, ...] = (),
    age_s: float = 12.0,
) -> UsageCacheEntry:
    """A fresh cache row — fetched just before the harness clock's now."""
    return replace(
        EMPTY_USAGE_CACHE_ENTRY,
        last_good=UsageSnapshot(
            UsageWindow(five_hour, "2026-10-10T22:30:00Z"),
            UsageWindow(seven_day, "2026-10-16T00:00:00Z"),
            scoped,
        ),
        fetched_at_s=1_000_000.0 - age_s,
    )


usage_cache = InMemoryUsageCache()
usage_cache.save(
    "work",
    _cached(73.0, 41.0, (ScopedWindow("Sonnet", 88.0, "2026-10-16T00:00:00Z"),)),
)
usage_cache.save("personal", _cached(12.0, 8.0, age_s=31.0))
usage_cache.save("backup", _cached(94.5, 87.0, age_s=47.0))

app, *_ = wired_app(
    Path("/tmp/cam-docs-shot"),
    names=("work", "personal", "backup"),
    active_name="work",
    usage_cache=usage_cache,
)
