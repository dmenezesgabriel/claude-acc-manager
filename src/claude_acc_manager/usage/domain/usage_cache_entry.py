"""Per-account cached usage measurement + fetch/backoff state.

Evidence: claude-swap ``usage_store.py``'s per-row shape (``UsageEntry``) —
"the store persists only *measurements* (``lastGood``) and *fetch state*
(failures, backoff, poll schedule)". Trimmed to what M5 needs: no claim
leases, no dead-token strike counters (plan §11 M5 decision 5 defers
quarantine persistence to M6/M9), no schema-version bookkeeping (that lives
in the ``FileUsageCache`` adapter, same split as ``file_account_store.py``).

Example:
    replace(EMPTY_USAGE_CACHE_ENTRY, last_good=snapshot, fetched_at_s=now)
"""

from dataclasses import dataclass

from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot


@dataclass(frozen=True)
class UsageCacheEntry:
    """One account's cached usage row.

    ``last_good`` and ``fetched_at_s`` are the last successful measurement;
    a failure never clears them (stale-on-error, claude-swap's rule).
    ``consecutive_failures``/``last_error``/``backoff_until_s``/
    ``last_429_at_s`` are fetch state. ``next_poll_at_s``/``poll_interval_s``
    are the cadence :mod:`services.poll_policy` last planned, persisted so
    every surface reading this cache inherits the same schedule.

    Example:
        UsageCacheEntry(snapshot, 1700000000.0, 0, None, None, None, None, None)
    """

    last_good: UsageSnapshot | None
    fetched_at_s: float | None
    consecutive_failures: int
    last_error: str | None
    backoff_until_s: float | None
    last_429_at_s: float | None
    next_poll_at_s: float | None
    poll_interval_s: float | None


EMPTY_USAGE_CACHE_ENTRY = UsageCacheEntry(
    last_good=None,
    fetched_at_s=None,
    consecutive_failures=0,
    last_error=None,
    backoff_until_s=None,
    last_429_at_s=None,
    next_poll_at_s=None,
    poll_interval_s=None,
)
