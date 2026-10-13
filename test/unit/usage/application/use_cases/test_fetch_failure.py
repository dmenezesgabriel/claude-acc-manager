"""``FetchAccountUsage`` failure modes — API errors, force-fetch override."""

from dataclasses import replace

from support.controllable_clock import ControllableClock
from support.fake_usage_api import FakeUsageApi
from support.fetch_usage_rig import SNAPSHOT as _SNAPSHOT
from support.fetch_usage_rig import iso as _iso
from support.fetch_usage_rig import make_use_case
from support.in_memory_usage_cache import InMemoryUsageCache

from claude_acc_manager.usage.application.ports import (
    AnthropicApiError,
    HttpTransportError,
)
from claude_acc_manager.usage.application.use_cases.fetch_account_usage import UsageReport
from claude_acc_manager.usage.domain.services import poll_policy
from claude_acc_manager.usage.domain.usage_cache_entry import EMPTY_USAGE_CACHE_ENTRY
from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot, UsageWindow


class TestFetchFailure:
    """429 is a throttle, not exhaustion: last-good is served while trusted.
    Other failures freeze last-good the same way, without arming the flat
    429 backoff."""

    def test_429_serves_the_frozen_last_good(self):
        cache = InMemoryUsageCache()
        cache.save(
            "work", replace(EMPTY_USAGE_CACHE_ENTRY, last_good=_SNAPSHOT, fetched_at_s=999_800.0)
        )
        use_case, _, _, _, cache, clock = make_use_case(
            usage_api=FakeUsageApi(error=AnthropicApiError(429, None)), cache=cache
        )

        report = use_case.execute("work", is_active=False)

        assert report == UsageReport(
            snapshot=_SNAPSHOT, stale=True, last_error="http-429", permanent_auth_error=False
        )

    def test_429_arms_the_flat_backoff_and_stamps_the_429_marker(self):
        cache = InMemoryUsageCache()
        cache.save(
            "work", replace(EMPTY_USAGE_CACHE_ENTRY, last_good=_SNAPSHOT, fetched_at_s=999_800.0)
        )
        use_case, _, _, _, cache, clock = make_use_case(
            usage_api=FakeUsageApi(error=AnthropicApiError(429, None)), cache=cache
        )

        use_case.execute("work", is_active=False)

        entry = cache.load("work")
        assert entry.consecutive_failures == 1
        assert entry.last_error == "http-429"
        assert entry.backoff_until_s == clock.now_epoch_s() + poll_policy.RATE_LIMIT_BACKOFF_S
        assert entry.last_429_at_s == clock.now_epoch_s()
        assert entry.last_good == _SNAPSHOT

    def test_429_without_a_prior_last_good_is_unknown(self):
        use_case, _, _, _, _, _ = make_use_case(
            usage_api=FakeUsageApi(error=AnthropicApiError(429, None))
        )

        report = use_case.execute("work", is_active=False)

        assert report == UsageReport(
            snapshot=None, stale=False, last_error="http-429", permanent_auth_error=False
        )

    def test_a_non_429_error_freezes_last_good_without_arming_the_429_backoff(self):
        cache = InMemoryUsageCache()
        cache.save(
            "work", replace(EMPTY_USAGE_CACHE_ENTRY, last_good=_SNAPSHOT, fetched_at_s=999_800.0)
        )
        use_case, _, _, _, cache, _ = make_use_case(
            usage_api=FakeUsageApi(error=AnthropicApiError(500, None)), cache=cache
        )

        report = use_case.execute("work", is_active=False)

        assert report == UsageReport(
            snapshot=_SNAPSHOT, stale=True, last_error="http-500", permanent_auth_error=False
        )
        entry = cache.load("work")
        assert entry.backoff_until_s is None
        assert entry.last_429_at_s is None

    def test_a_network_failure_is_reported_as_network(self):
        cache = InMemoryUsageCache()
        cache.save(
            "work", replace(EMPTY_USAGE_CACHE_ENTRY, last_good=_SNAPSHOT, fetched_at_s=999_800.0)
        )
        use_case, _, _, _, cache, _ = make_use_case(
            usage_api=FakeUsageApi(error=HttpTransportError("timed out")), cache=cache
        )

        report = use_case.execute("work", is_active=False)

        assert report == UsageReport(
            snapshot=_SNAPSHOT, stale=True, last_error="network", permanent_auth_error=False
        )

    def test_a_network_failure_does_not_arm_the_429_backoff(self):
        # distinguishes the HttpTransportError branch from the 429 one: a
        # timeout is recorded for the right account, but never mistaken for
        # a rate limit
        cache = InMemoryUsageCache()
        cache.save(
            "work", replace(EMPTY_USAGE_CACHE_ENTRY, last_good=_SNAPSHOT, fetched_at_s=999_800.0)
        )
        use_case, _, _, _, cache, _ = make_use_case(
            usage_api=FakeUsageApi(error=HttpTransportError("timed out")), cache=cache
        )

        use_case.execute("work", is_active=False)

        entry = cache.load("work")
        assert entry.consecutive_failures == 1
        assert entry.backoff_until_s is None
        assert entry.last_429_at_s is None

    def test_last_good_beyond_the_trust_ceiling_is_unknown(self):
        cache = InMemoryUsageCache()
        clock = ControllableClock(now_epoch_s=1_000_000.0)
        cache.save(
            "work",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                last_good=_SNAPSHOT,
                fetched_at_s=clock.now_epoch_s() - poll_policy.TRUST_MAX_AGE_S,
            ),
        )
        use_case, _, _, _, cache, _ = make_use_case(
            usage_api=FakeUsageApi(error=AnthropicApiError(429, None)), cache=cache, clock=clock
        )

        report = use_case.execute("work", is_active=False)

        assert report == UsageReport(
            snapshot=None, stale=False, last_error="http-429", permanent_auth_error=False
        )

    def test_a_reset_that_already_passed_ends_trust_early(self):
        # a recent fetch (well within the age ceiling) whose own window
        # reset a moment ago is still obsolete data -- age alone would say
        # "trust it", but the reset must end trust regardless
        clock = ControllableClock(now_epoch_s=1_000_000.0)
        snapshot = UsageSnapshot(
            five_hour=UsageWindow(pct=50.0, resets_at=_iso(clock.now_epoch_s() - 10.0)),
            seven_day=None,
            scoped=(),
        )
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                last_good=snapshot,
                fetched_at_s=clock.now_epoch_s() - 200.0,
            ),
        )
        use_case, _, _, _, cache, _ = make_use_case(
            usage_api=FakeUsageApi(error=AnthropicApiError(429, None)), cache=cache, clock=clock
        )

        report = use_case.execute("work", is_active=False)

        assert report == UsageReport(
            snapshot=None, stale=False, last_error="http-429", permanent_auth_error=False
        )

    def test_consecutive_failures_accumulate_across_repeated_errors(self):
        # the second attempt must leave the armed backoff first — a gated
        # skip is not a failure and does not accumulate
        clock = ControllableClock(now_epoch_s=1_000_000.0)
        use_case, _, _, _, cache, _ = make_use_case(
            usage_api=FakeUsageApi(error=AnthropicApiError(429, None)), clock=clock
        )

        use_case.execute("work", is_active=False)
        clock.advance(poll_policy.RATE_LIMIT_BACKOFF_S)
        use_case.execute("work", is_active=False)

        assert cache.load("work").consecutive_failures == 2


class TestForceFetch:
    """``force=True`` skips the freshness/plan gates — never the 429 backoff."""

    def test_force_fetches_despite_a_fresh_entry(self):
        # arrange — an entry inside SERVE_TTL would normally serve untouched
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(EMPTY_USAGE_CACHE_ENTRY, last_good=_SNAPSHOT, fetched_at_s=999_900.0),
        )
        use_case, usage_api, _, _, _, _ = make_use_case(cache=cache)

        # act
        report = use_case.execute("work", is_active=False, force=True)

        # assert
        assert report.stale is False
        assert len(usage_api.requests) == 1

    def test_force_fetches_despite_a_parked_plan(self):
        # arrange — next_poll_at parked ahead; force still fetches (escalated refresh)
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                last_good=_SNAPSHOT,
                fetched_at_s=999_000.0,
                next_poll_at_s=1_000_100.0,
            ),
        )
        use_case, usage_api, _, _, _, _ = make_use_case(cache=cache)

        # act
        report = use_case.execute("work", is_active=False, force=True)

        # assert — a real fetch happened, not a frozen serve
        assert report.stale is False and report.last_error is None
        assert len(usage_api.requests) == 1

    def test_force_never_bypasses_a_429_backoff(self):
        # arrange — the armed backoff is a live hold force must not break
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                last_good=_SNAPSHOT,
                fetched_at_s=999_000.0,
                backoff_until_s=1_000_100.0,
                last_error="http-429",
            ),
        )
        use_case, usage_api, _, _, _, _ = make_use_case(cache=cache)

        # act
        report = use_case.execute("work", is_active=False, force=True)

        # assert
        assert usage_api.requests == []
        assert report.last_error == "http-429"

    def test_no_force_keeps_the_normal_gates(self):
        # arrange — same parked entry, default call → plan governs
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                last_good=_SNAPSHOT,
                fetched_at_s=999_000.0,
                next_poll_at_s=1_000_100.0,
            ),
        )
        use_case, usage_api, _, _, _, _ = make_use_case(cache=cache)

        # act
        report = use_case.execute("work", is_active=False)

        # assert
        assert usage_api.requests == []
        assert report.last_error == "not-due"
