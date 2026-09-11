"""Unit tests for usage.application.use_cases.fetch_account_usage."""

from dataclasses import replace
from datetime import UTC, datetime

from support.controllable_clock import ControllableClock
from support.fake_credential_store import FakeCredentialStore
from support.fake_usage_api import FakeUsageApi
from support.in_memory_usage_cache import InMemoryUsageCache

from claude_acc_manager.usage.application.use_cases.fetch_account_usage import (
    FetchAccountUsage,
    UsageReport,
)
from claude_acc_manager.usage.domain.oauth_credential import StoredOAuthCredential
from claude_acc_manager.usage.domain.services import poll_policy
from claude_acc_manager.usage.domain.usage_cache_entry import EMPTY_USAGE_CACHE_ENTRY
from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot, UsageWindow

_SNAPSHOT = UsageSnapshot(
    five_hour=UsageWindow(pct=10.0, resets_at=None), seven_day=None, scoped=()
)
_CREDENTIAL = StoredOAuthCredential(access_token="at-1", refresh_token="rt-1", expires_at_ms=None)
HALF = lambda: 0.5  # noqa: E731 — jitter factor exactly 1.0


def _iso(epoch_s: float) -> str:
    return datetime.fromtimestamp(epoch_s, tz=UTC).isoformat().replace("+00:00", "Z")


def make_use_case(
    *,
    usage_api: FakeUsageApi | None = None,
    credentials: FakeCredentialStore | None = None,
    cache: InMemoryUsageCache | None = None,
    clock: ControllableClock | None = None,
) -> tuple[
    FetchAccountUsage, FakeUsageApi, FakeCredentialStore, InMemoryUsageCache, ControllableClock
]:
    usage_api = usage_api or FakeUsageApi(snapshot=_SNAPSHOT)
    credentials = credentials or FakeCredentialStore(credentials={"work": _CREDENTIAL})
    cache = cache or InMemoryUsageCache()
    clock = clock or ControllableClock(now_epoch_s=1_000_000.0)
    use_case = FetchAccountUsage(usage_api, credentials, cache, clock, rng=HALF)
    return use_case, usage_api, credentials, cache, clock


class TestServesFreshCacheWithoutFetching:
    def test_returns_the_cached_snapshot(self):
        # arrange
        clock = ControllableClock(now_epoch_s=1_000_000.0)
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(EMPTY_USAGE_CACHE_ENTRY, last_good=_SNAPSHOT, fetched_at_s=1_000_000.0 - 10.0),
        )
        use_case, usage_api, _, _, _ = make_use_case(cache=cache, clock=clock)

        # act
        report = use_case.execute("work", is_active=False)

        # assert
        assert report == UsageReport(
            snapshot=_SNAPSHOT, stale=False, last_error=None, permanent_auth_error=False
        )
        assert usage_api.requests == []


class TestFetchesAndCachesOnAStaleCache:
    def test_returns_the_fetched_snapshot(self):
        use_case, _, _, _, _ = make_use_case()
        report = use_case.execute("work", is_active=False)
        assert report == UsageReport(
            snapshot=_SNAPSHOT, stale=False, last_error=None, permanent_auth_error=False
        )

    def test_fetches_with_the_stored_access_token(self):
        use_case, usage_api, _, _, _ = make_use_case()
        use_case.execute("work", is_active=False)
        assert usage_api.requests == ["at-1"]

    def test_saves_the_snapshot_and_fetch_timestamp_to_the_cache(self):
        use_case, _, _, cache, clock = make_use_case()
        use_case.execute("work", is_active=False)
        entry = cache.load("work")
        assert entry.last_good == _SNAPSHOT
        assert entry.fetched_at_s == clock.now_epoch_s()

    def test_saves_a_poll_plan_from_the_fresh_fetch(self):
        # no prior interval, no movement signal, no reset -> the plain
        # candidate default, jittered by 1.0 (rng pinned at the midpoint)
        use_case, _, _, cache, clock = make_use_case()
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
        use_case, _, _, cache, _ = make_use_case(cache=cache)

        report = use_case.execute("work", is_active=False)

        assert report.snapshot == _SNAPSHOT
        assert cache.load("work").last_good == _SNAPSHOT


class TestPollPlanThreadsThroughEveryFactor:
    """Pins that every plan_after_fetch input is the real one, not dropped."""

    def test_movement_uses_the_prior_interval_and_both_pcts(self):
        # arrange — a prior fetch at pct=10 with a learned 500s interval;
        # movement to pct=20 halves it: max(MIN_INTERVAL_S, 500/2) = 250
        prior_snapshot = UsageSnapshot(
            five_hour=UsageWindow(pct=10.0, resets_at=None), seven_day=None, scoped=()
        )
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                last_good=prior_snapshot,
                fetched_at_s=0.0,
                poll_interval_s=500.0,
            ),
        )
        new_snapshot = UsageSnapshot(
            five_hour=UsageWindow(pct=20.0, resets_at=None), seven_day=None, scoped=()
        )
        use_case, _, _, cache, _ = make_use_case(
            usage_api=FakeUsageApi(snapshot=new_snapshot), cache=cache
        )

        # act
        use_case.execute("work", is_active=False)

        # assert
        assert cache.load("work").poll_interval_s == 250.0

    def test_is_active_selects_the_ceiling(self):
        # arrange — no movement, a large prior interval, so the result is
        # clamped to the account-kind ceiling
        cache = InMemoryUsageCache()
        snapshot = UsageSnapshot(
            five_hour=UsageWindow(pct=10.0, resets_at=None), seven_day=None, scoped=()
        )
        cache.save(
            "work",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                last_good=snapshot,
                fetched_at_s=0.0,
                poll_interval_s=10_000.0,
            ),
        )
        use_case, _, _, cache, _ = make_use_case(
            usage_api=FakeUsageApi(snapshot=snapshot), cache=cache
        )

        # act
        use_case.execute("work", is_active=True)

        # assert
        assert cache.load("work").poll_interval_s == poll_policy.ACTIVE_MAX_INTERVAL_S

    def test_headroom_floors_the_interval_when_exhausted(self):
        maxed = UsageSnapshot(
            five_hour=UsageWindow(pct=100.0, resets_at=None), seven_day=None, scoped=()
        )
        use_case, _, _, cache, _ = make_use_case(usage_api=FakeUsageApi(snapshot=maxed))

        use_case.execute("work", is_active=False)

        assert cache.load("work").poll_interval_s == poll_policy.EXHAUSTED_INTERVAL_S

    def test_an_exhausted_reset_caps_the_next_poll(self):
        # arrange — maxed and resetting sooner than EXHAUSTED_INTERVAL_S away
        clock = ControllableClock(now_epoch_s=1_000_000.0)
        reset_s = clock.now_epoch_s() + 90.0
        maxed = UsageSnapshot(
            five_hour=UsageWindow(pct=100.0, resets_at=_iso(reset_s)), seven_day=None, scoped=()
        )
        use_case, _, _, cache, _ = make_use_case(
            usage_api=FakeUsageApi(snapshot=maxed), clock=clock
        )

        # act
        use_case.execute("work", is_active=False)

        # assert
        entry = cache.load("work")
        assert entry.next_poll_at_s == reset_s + poll_policy.RESET_SLACK_S

    def test_a_non_exhausted_reset_caps_the_next_poll(self):
        clock = ControllableClock(now_epoch_s=1_000_000.0)
        reset_s = clock.now_epoch_s() + 90.0
        snapshot = UsageSnapshot(
            five_hour=UsageWindow(pct=10.0, resets_at=_iso(reset_s)), seven_day=None, scoped=()
        )
        use_case, _, _, cache, _ = make_use_case(
            usage_api=FakeUsageApi(snapshot=snapshot), clock=clock
        )

        use_case.execute("work", is_active=False)

        entry = cache.load("work")
        assert entry.next_poll_at_s == reset_s + poll_policy.RESET_SLACK_S

    def test_a_recent_429_floors_the_interval_via_aimd(self):
        # arrange — no movement (default base 300), but a 429 10s ago is
        # still "recent": AIMD grows it to max(300*1.5, 360) = 450
        clock = ControllableClock(now_epoch_s=1_000_000.0)
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(EMPTY_USAGE_CACHE_ENTRY, last_429_at_s=clock.now_epoch_s() - 10.0),
        )
        use_case, _, _, cache, _ = make_use_case(cache=cache, clock=clock)

        use_case.execute("work", is_active=False)

        assert cache.load("work").poll_interval_s == 450.0

    def test_last_429_at_s_survives_a_successful_fetch(self):
        # a success clears failure state, but never this stamp (claude-swap's
        # deliberate rule — cache_trust.recent_429 needs it to stay put)
        cache = InMemoryUsageCache()
        cache.save("work", replace(EMPTY_USAGE_CACHE_ENTRY, last_429_at_s=123.0))
        use_case, _, _, cache, _ = make_use_case(cache=cache)

        use_case.execute("work", is_active=False)

        assert cache.load("work").last_429_at_s == 123.0


class TestNoCredential:
    def test_no_stored_credential_reports_no_credential(self):
        use_case, usage_api, _, _, _ = make_use_case(credentials=FakeCredentialStore())
        report = use_case.execute("work", is_active=False)
        assert report == UsageReport(
            snapshot=None, stale=False, last_error="no-credential", permanent_auth_error=False
        )
        assert usage_api.requests == []

    def test_falls_back_to_a_stale_last_good_when_no_credential_is_found(self):
        cache = InMemoryUsageCache()
        cache.save("work", replace(EMPTY_USAGE_CACHE_ENTRY, last_good=_SNAPSHOT, fetched_at_s=0.0))
        use_case, _, _, _, _ = make_use_case(credentials=FakeCredentialStore(), cache=cache)

        report = use_case.execute("work", is_active=False)

        assert report == UsageReport(
            snapshot=_SNAPSHOT, stale=True, last_error="no-credential", permanent_auth_error=False
        )
