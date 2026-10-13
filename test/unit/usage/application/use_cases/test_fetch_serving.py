"""``FetchAccountUsage`` — what gets served: fresh cache, gates, escalation.

Eligibility decides whether a fetch happens at all; a stale cache refetches
and re-caches, and the constructor threshold feeds the urgent-escalation
band.
"""

from dataclasses import replace

from support.controllable_clock import ControllableClock
from support.fake_credential_store import FakeCredentialStore
from support.fake_usage_api import FakeUsageApi
from support.fetch_usage_rig import SNAPSHOT as _SNAPSHOT
from support.fetch_usage_rig import iso as _iso
from support.fetch_usage_rig import make_use_case
from support.in_memory_usage_cache import InMemoryUsageCache

from claude_acc_manager.usage.application.use_cases.fetch_account_usage import UsageReport
from claude_acc_manager.usage.domain.services import poll_policy
from claude_acc_manager.usage.domain.usage_cache_entry import EMPTY_USAGE_CACHE_ENTRY
from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot, UsageWindow


class TestServesFreshCacheWithoutFetching:
    def test_returns_the_cached_snapshot(self):
        # arrange
        clock = ControllableClock(now_epoch_s=1_000_000.0)
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(EMPTY_USAGE_CACHE_ENTRY, last_good=_SNAPSHOT, fetched_at_s=1_000_000.0 - 10.0),
        )
        use_case, usage_api, _, _, _, _ = make_use_case(cache=cache, clock=clock)

        # act
        report = use_case.execute("work", is_active=False)

        # assert
        assert report == UsageReport(
            snapshot=_SNAPSHOT, stale=False, last_error=None, permanent_auth_error=False
        )
        assert usage_api.requests == []


class TestFetchEligibilityGates:
    """Past the serve TTL, the persisted plan decides whether a fetch is
    even attempted: `in_backoff` first, then `poll_due`. A skipped attempt
    is not a failure — it touches neither the network nor the entry."""

    def test_an_armed_backoff_serves_last_good_without_fetching(self):
        # arrange — a 429 armed a flat backoff that is still in force
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                last_good=_SNAPSHOT,
                fetched_at_s=999_000.0,
                consecutive_failures=1,
                last_error="http-429",
                backoff_until_s=1_000_100.0,
                last_429_at_s=999_800.0,
            ),
        )
        use_case, usage_api, _, _, cache, _ = make_use_case(cache=cache)

        # act
        report = use_case.execute("work", is_active=False)

        # assert — frozen serve names the recorded error, not the gate word
        assert report == UsageReport(
            snapshot=_SNAPSHOT,
            stale=True,
            last_error="http-429",
            permanent_auth_error=False,
        )
        assert usage_api.requests == []
        entry = cache.load("work")
        assert entry.consecutive_failures == 1
        assert entry.backoff_until_s == 1_000_100.0

    def test_a_backoff_without_a_recorded_error_names_the_gate(self):
        # backoff armed but last_error cleared — the report still explains
        # why the data is old
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                last_good=_SNAPSHOT,
                fetched_at_s=999_000.0,
                backoff_until_s=1_000_100.0,
            ),
        )
        use_case, _, _, _, _, _ = make_use_case(cache=cache)

        report = use_case.execute("work", is_active=False)

        assert report == UsageReport(
            snapshot=_SNAPSHOT,
            stale=True,
            last_error="backoff",
            permanent_auth_error=False,
        )

    def test_a_backoff_past_the_trust_ceiling_reports_unknown(self):
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                last_good=_SNAPSHOT,
                fetched_at_s=1_000_000.0 - poll_policy.TRUST_MAX_AGE_S,
                last_error="http-429",
                backoff_until_s=1_000_100.0,
            ),
        )
        use_case, _, _, _, _, _ = make_use_case(cache=cache)

        report = use_case.execute("work", is_active=False)

        assert report == UsageReport(
            snapshot=None,
            stale=False,
            last_error="http-429",
            permanent_auth_error=False,
        )

    def test_a_plan_not_yet_due_serves_last_good_without_fetching(self):
        # arrange — stale data, but the plan parked this account
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                last_good=_SNAPSHOT,
                fetched_at_s=999_000.0,
                poll_interval_s=300.0,
                next_poll_at_s=1_000_100.0,
            ),
        )
        use_case, usage_api, _, _, cache, _ = make_use_case(cache=cache)

        # act
        report = use_case.execute("work", is_active=False)

        # assert
        assert report == UsageReport(
            snapshot=_SNAPSHOT,
            stale=True,
            last_error="not-due",
            permanent_auth_error=False,
        )
        assert usage_api.requests == []
        assert cache.load("work").consecutive_failures == 0

    def test_not_due_keeps_the_recorded_failure_word(self):
        # a parked plan whose last attempt failed names that failure
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                last_good=_SNAPSHOT,
                fetched_at_s=999_000.0,
                last_error="network",
                next_poll_at_s=1_000_100.0,
            ),
        )
        use_case, _, _, _, _, _ = make_use_case(cache=cache)

        report = use_case.execute("work", is_active=False)

        assert report == UsageReport(
            snapshot=_SNAPSHOT,
            stale=True,
            last_error="network",
            permanent_auth_error=False,
        )

    def test_backoff_is_checked_before_the_plan(self):
        # both armed at once — the backoff word wins (it names a live hold;
        # a future deadline alone is just scheduling)
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                last_good=_SNAPSHOT,
                fetched_at_s=999_000.0,
                backoff_until_s=1_000_100.0,
                next_poll_at_s=1_000_100.0,
            ),
        )
        use_case, _, _, _, _, _ = make_use_case(cache=cache)

        report = use_case.execute("work", is_active=False)

        assert report.last_error == "backoff"

    def test_not_due_and_untrusted_reports_unknown(self):
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                last_good=_SNAPSHOT,
                fetched_at_s=1_000_000.0 - poll_policy.TRUST_MAX_AGE_S,
                next_poll_at_s=1_000_100.0,
            ),
        )
        use_case, _, _, _, _, _ = make_use_case(cache=cache)

        report = use_case.execute("work", is_active=False)

        assert report == UsageReport(
            snapshot=None,
            stale=False,
            last_error="not-due",
            permanent_auth_error=False,
        )

    def test_not_due_and_past_reset_reports_unknown(self):
        # a parked plan does not resurrect data whose own window already
        # rolled over — the reset ends trust before the age ceiling does
        snapshot = UsageSnapshot(
            five_hour=UsageWindow(pct=50.0, resets_at=_iso(1_000_000.0 - 10.0)),
            seven_day=None,
            scoped=(),
        )
        # fetched 200s ago: past the serve TTL but inside the trust ceiling —
        # only the passed reset can refuse the frozen serve
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                last_good=snapshot,
                fetched_at_s=999_800.0,
                next_poll_at_s=1_000_100.0,
            ),
        )
        use_case, usage_api, _, _, _, _ = make_use_case(cache=cache)

        report = use_case.execute("work", is_active=False)

        assert report == UsageReport(
            snapshot=None,
            stale=False,
            last_error="not-due",
            permanent_auth_error=False,
        )
        assert usage_api.requests == []

    def test_a_plan_at_its_deadline_fetches(self):
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                last_good=_SNAPSHOT,
                fetched_at_s=999_000.0,
                next_poll_at_s=1_000_000.0,
            ),
        )
        use_case, usage_api, _, _, _, _ = make_use_case(cache=cache)

        report = use_case.execute("work", is_active=False)

        assert usage_api.requests == ["at-1"]
        assert report.snapshot == _SNAPSHOT

    def test_backoff_past_its_deadline_fetches(self):
        # the flat backoff expired -> the plan is consulted, and a never-
        # planned entry fetches
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                last_good=_SNAPSHOT,
                fetched_at_s=999_000.0,
                backoff_until_s=1_000_000.0,
            ),
        )
        use_case, usage_api, _, _, _, _ = make_use_case(cache=cache)

        use_case.execute("work", is_active=False)

        assert usage_api.requests == ["at-1"]


class TestFetchesAndCachesOnAStaleCache:
    def test_returns_the_fetched_snapshot(self):
        use_case, _, _, _, _, _ = make_use_case()
        report = use_case.execute("work", is_active=False)
        assert report == UsageReport(
            snapshot=_SNAPSHOT, stale=False, last_error=None, permanent_auth_error=False
        )

    def test_fetches_with_the_stored_access_token(self):
        use_case, usage_api, _, _, _, _ = make_use_case()
        use_case.execute("work", is_active=False)
        assert usage_api.requests == ["at-1"]

    def test_saves_the_snapshot_and_fetch_timestamp_to_the_cache(self):
        use_case, _, _, _, cache, clock = make_use_case()
        use_case.execute("work", is_active=False)
        entry = cache.load("work")
        assert entry.last_good == _SNAPSHOT
        assert entry.fetched_at_s == clock.now_epoch_s()

    def test_saves_a_poll_plan_from_the_fresh_fetch(self):
        # no prior interval, no movement signal, no reset -> the plain
        # candidate default, jittered by 1.0 (rng pinned at the midpoint)
        use_case, _, _, _, cache, clock = make_use_case()
        use_case.execute("work", is_active=False)
        entry = cache.load("work")
        assert entry.poll_interval_s == poll_policy.CANDIDATE_DEFAULT_INTERVAL_S
        assert (
            entry.next_poll_at_s == clock.now_epoch_s() + poll_policy.CANDIDATE_DEFAULT_INTERVAL_S
        )

    def test_a_stale_but_present_cache_entry_is_still_overwritten(self):
        cache = InMemoryUsageCache()
        old_snapshot = UsageSnapshot(
            five_hour=UsageWindow(pct=5.0, resets_at=None), seven_day=None, scoped=()
        )
        cache.save(
            "work",
            replace(EMPTY_USAGE_CACHE_ENTRY, last_good=old_snapshot, fetched_at_s=0.0),
        )
        use_case, _, _, _, cache, _ = make_use_case(cache=cache)

        report = use_case.execute("work", is_active=False)

        assert report.snapshot == _SNAPSHOT
        assert cache.load("work").last_good == _SNAPSHOT


class TestNoCredential:
    def test_no_stored_credential_reports_no_credential(self):
        use_case, usage_api, _, _, _, _ = make_use_case(credentials=FakeCredentialStore())
        report = use_case.execute("work", is_active=False)
        assert report == UsageReport(
            snapshot=None, stale=False, last_error="no-credential", permanent_auth_error=False
        )
        assert usage_api.requests == []

    def test_falls_back_to_a_stale_last_good_when_no_credential_is_found(self):
        cache = InMemoryUsageCache()
        cache.save("work", replace(EMPTY_USAGE_CACHE_ENTRY, last_good=_SNAPSHOT, fetched_at_s=0.0))
        use_case, _, _, _, _, _ = make_use_case(credentials=FakeCredentialStore(), cache=cache)

        report = use_case.execute("work", is_active=False)

        assert report == UsageReport(
            snapshot=_SNAPSHOT, stale=True, last_error="no-credential", permanent_auth_error=False
        )


class TestUrgentThreshold:
    """The constructor threshold feeds plan_after_fetch's escalation band."""

    def test_active_moving_into_the_band_plans_urgently(self):
        # arrange — active account burns 80→82 with threshold 90 (band 75+)
        api = FakeUsageApi(
            snapshot=UsageSnapshot(
                five_hour=UsageWindow(pct=82.0, resets_at=None), seven_day=None, scoped=()
            )
        )
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                last_good=UsageSnapshot(
                    five_hour=UsageWindow(pct=80.0, resets_at=None), seven_day=None, scoped=()
                ),
                fetched_at_s=999_000.0,
            ),
        )
        use_case, _, _, _, cache, _ = make_use_case(usage_api=api, cache=cache)

        # act
        use_case.execute("work", is_active=True, threshold=90.0)

        # assert
        assert cache.load("work").poll_interval_s == poll_policy.URGENT_INTERVAL_S

    def test_outside_the_band_plans_normally(self):
        # arrange — same shape, binding pct below the band
        api = FakeUsageApi(
            snapshot=UsageSnapshot(
                five_hour=UsageWindow(pct=40.0, resets_at=None), seven_day=None, scoped=()
            )
        )
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                last_good=UsageSnapshot(
                    five_hour=UsageWindow(pct=30.0, resets_at=None), seven_day=None, scoped=()
                ),
                fetched_at_s=999_000.0,
            ),
        )
        use_case, _, _, _, cache, _ = make_use_case(usage_api=api, cache=cache)

        # act
        use_case.execute("work", is_active=True, threshold=90.0)

        # assert — movement halving of the 180s default, not the 60s urgent floor
        assert cache.load("work").poll_interval_s == poll_policy.MIN_INTERVAL_S

    def test_constructor_threshold_feeds_the_band(self):
        # arrange — active burns 80→82; ctor threshold 90 puts 82 inside the band
        api = FakeUsageApi(
            snapshot=UsageSnapshot(
                five_hour=UsageWindow(pct=82.0, resets_at=None), seven_day=None, scoped=()
            )
        )
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                last_good=UsageSnapshot(
                    five_hour=UsageWindow(pct=80.0, resets_at=None), seven_day=None, scoped=()
                ),
                fetched_at_s=999_000.0,
            ),
        )
        use_case, _, _, _, cache, _ = make_use_case(usage_api=api, cache=cache)

        # act — no per-call override: the wired threshold must reach the planner
        use_case.execute("work", is_active=True)

        # assert
        assert cache.load("work").poll_interval_s == poll_policy.URGENT_INTERVAL_S

    def test_per_call_threshold_overrides_the_constructor(self):
        # arrange — 62% is inside the band for a 70 threshold (55+) but not 90 (75+)
        api = FakeUsageApi(
            snapshot=UsageSnapshot(
                five_hour=UsageWindow(pct=62.0, resets_at=None), seven_day=None, scoped=()
            )
        )
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                last_good=UsageSnapshot(
                    five_hour=UsageWindow(pct=60.0, resets_at=None), seven_day=None, scoped=()
                ),
                fetched_at_s=999_000.0,
            ),
        )
        use_case, _, _, _, cache, _ = make_use_case(usage_api=api, cache=cache)

        # act
        use_case.execute("work", is_active=True, threshold=70.0)

        # assert — urgent because the call's 70 won, not the wired 90
        assert cache.load("work").poll_interval_s == poll_policy.URGENT_INTERVAL_S
