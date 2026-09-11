"""Unit tests for usage.domain.usage_cache_entry."""

from claude_acc_manager.usage.domain.usage_cache_entry import (
    EMPTY_USAGE_CACHE_ENTRY,
    UsageCacheEntry,
)


class TestEmptyUsageCacheEntry:
    def test_carries_no_measurement_or_failure_state(self):
        assert EMPTY_USAGE_CACHE_ENTRY == UsageCacheEntry(
            last_good=None,
            fetched_at_s=None,
            consecutive_failures=0,
            last_error=None,
            backoff_until_s=None,
            last_429_at_s=None,
            next_poll_at_s=None,
            poll_interval_s=None,
        )
