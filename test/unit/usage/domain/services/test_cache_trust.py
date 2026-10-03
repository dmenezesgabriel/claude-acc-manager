"""Unit tests for usage.domain.services.cache_trust.

The trust contract over our UsageCacheEntry: freshness, the armed-backoff
window, recent-429 recency, and how long a frozen last_good stays
decision-grade.
"""

from dataclasses import replace

from claude_acc_manager.usage.domain.services.cache_trust import (
    in_backoff,
    is_fresh,
    recent_429,
    trust_ok,
)
from claude_acc_manager.usage.domain.usage_cache_entry import EMPTY_USAGE_CACHE_ENTRY
from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot

NOW = 1_000_000.0
_SNAPSHOT = UsageSnapshot(five_hour=None, seven_day=None, scoped=())


class TestIsFresh:
    def test_never_fetched_is_not_fresh(self):
        assert is_fresh(EMPTY_USAGE_CACHE_ENTRY, NOW, ttl_s=180.0) is False

    def test_within_the_ttl_is_fresh(self):
        entry = replace(EMPTY_USAGE_CACHE_ENTRY, fetched_at_s=NOW - 179.0)
        assert is_fresh(entry, NOW, ttl_s=180.0) is True

    def test_at_the_ttl_boundary_is_not_fresh(self):
        entry = replace(EMPTY_USAGE_CACHE_ENTRY, fetched_at_s=NOW - 180.0)
        assert is_fresh(entry, NOW, ttl_s=180.0) is False

    def test_past_the_ttl_is_not_fresh(self):
        entry = replace(EMPTY_USAGE_CACHE_ENTRY, fetched_at_s=NOW - 181.0)
        assert is_fresh(entry, NOW, ttl_s=180.0) is False


class TestInBackoff:
    def test_no_backoff_set_is_not_in_backoff(self):
        assert in_backoff(EMPTY_USAGE_CACHE_ENTRY, NOW) is False

    def test_before_the_deadline_is_in_backoff(self):
        entry = replace(EMPTY_USAGE_CACHE_ENTRY, backoff_until_s=NOW + 1.0)
        assert in_backoff(entry, NOW) is True

    def test_at_the_deadline_is_not_in_backoff(self):
        entry = replace(EMPTY_USAGE_CACHE_ENTRY, backoff_until_s=NOW)
        assert in_backoff(entry, NOW) is False

    def test_past_the_deadline_is_not_in_backoff(self):
        entry = replace(EMPTY_USAGE_CACHE_ENTRY, backoff_until_s=NOW - 1.0)
        assert in_backoff(entry, NOW) is False


class TestRecent429:
    def test_never_429d_is_not_recent(self):
        assert recent_429(EMPTY_USAGE_CACHE_ENTRY, NOW, window_s=3600.0) is False

    def test_within_the_window_of_the_429_stamp_is_recent(self):
        entry = replace(EMPTY_USAGE_CACHE_ENTRY, last_429_at_s=NOW - 3599.0)
        assert recent_429(entry, NOW, window_s=3600.0) is True

    def test_at_the_window_boundary_is_not_recent(self):
        entry = replace(EMPTY_USAGE_CACHE_ENTRY, last_429_at_s=NOW - 3600.0)
        assert recent_429(entry, NOW, window_s=3600.0) is False

    def test_past_the_window_is_not_recent(self):
        entry = replace(EMPTY_USAGE_CACHE_ENTRY, last_429_at_s=NOW - 3601.0)
        assert recent_429(entry, NOW, window_s=3600.0) is False

    def test_anchors_on_the_honored_backoff_deadline_when_later(self):
        # a hard 429 block honored for an hour keeps recency alive until the
        # block itself lifts, not just from the original 429 timestamp
        entry = replace(
            EMPTY_USAGE_CACHE_ENTRY,
            last_429_at_s=NOW - 4000.0,
            last_error="http-429",
            backoff_until_s=NOW - 100.0,
        )
        assert recent_429(entry, NOW, window_s=3600.0) is True

    def test_a_later_unrelated_failure_does_not_re_arm_recency(self):
        # backoff_until was set by a later NON-429 failure — must not extend
        # the anchor past the original 429 stamp
        entry = replace(
            EMPTY_USAGE_CACHE_ENTRY,
            last_429_at_s=NOW - 4000.0,
            last_error="network",
            backoff_until_s=NOW + 100.0,
        )
        assert recent_429(entry, NOW, window_s=3600.0) is False


class TestTrustOk:
    def test_no_last_good_is_never_trusted(self):
        assert (
            trust_ok(EMPTY_USAGE_CACHE_ENTRY, NOW, earliest_reset_s=None, ceiling_s=3600.0) is False
        )

    def test_last_good_without_a_fetch_timestamp_is_never_trusted(self):
        # pins the `or`, not `and`: last_good alone must not be enough
        entry = replace(EMPTY_USAGE_CACHE_ENTRY, last_good=_SNAPSHOT)
        assert trust_ok(entry, NOW, earliest_reset_s=None, ceiling_s=3600.0) is False

    def test_fetch_timestamp_without_last_good_is_never_trusted(self):
        entry = replace(EMPTY_USAGE_CACHE_ENTRY, fetched_at_s=NOW - 100.0)
        assert trust_ok(entry, NOW, earliest_reset_s=None, ceiling_s=3600.0) is False

    def test_within_ceiling_and_no_known_reset_is_trusted(self):
        entry = replace(EMPTY_USAGE_CACHE_ENTRY, last_good=_SNAPSHOT, fetched_at_s=NOW - 100.0)
        assert trust_ok(entry, NOW, earliest_reset_s=None, ceiling_s=3600.0) is True

    def test_at_the_ceiling_boundary_is_not_trusted(self):
        entry = replace(EMPTY_USAGE_CACHE_ENTRY, last_good=_SNAPSHOT, fetched_at_s=NOW - 3600.0)
        assert trust_ok(entry, NOW, earliest_reset_s=None, ceiling_s=3600.0) is False

    def test_before_a_future_reset_is_trusted(self):
        entry = replace(EMPTY_USAGE_CACHE_ENTRY, last_good=_SNAPSHOT, fetched_at_s=NOW - 100.0)
        assert trust_ok(entry, NOW, earliest_reset_s=NOW + 1.0, ceiling_s=3600.0) is True

    def test_at_or_past_a_reset_is_not_trusted(self):
        entry = replace(EMPTY_USAGE_CACHE_ENTRY, last_good=_SNAPSHOT, fetched_at_s=NOW - 100.0)
        assert trust_ok(entry, NOW, earliest_reset_s=NOW, ceiling_s=3600.0) is False
