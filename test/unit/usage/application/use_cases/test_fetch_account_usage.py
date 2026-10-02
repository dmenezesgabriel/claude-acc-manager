"""Unit tests for usage.application.use_cases.fetch_account_usage."""

from dataclasses import replace
from datetime import UTC, datetime

from support.controllable_clock import ControllableClock
from support.fake_credential_store import FakeCredentialStore
from support.fake_token_refresher import FakeTokenRefresher
from support.fake_usage_api import FakeUsageApi
from support.in_memory_usage_cache import InMemoryUsageCache

from claude_acc_manager.usage.application.ports import (
    AnthropicApiError,
    HttpTransportError,
    RefreshedTokens,
)
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
    refresher: FakeTokenRefresher | None = None,
    credentials: FakeCredentialStore | None = None,
    cache: InMemoryUsageCache | None = None,
    clock: ControllableClock | None = None,
) -> tuple[
    FetchAccountUsage,
    FakeUsageApi,
    FakeTokenRefresher,
    FakeCredentialStore,
    InMemoryUsageCache,
    ControllableClock,
]:
    usage_api = usage_api or FakeUsageApi(snapshot=_SNAPSHOT)
    refresher = refresher or FakeTokenRefresher()
    credentials = credentials or FakeCredentialStore(credentials={"work": _CREDENTIAL})
    cache = cache or InMemoryUsageCache()
    clock = clock or ControllableClock(now_epoch_s=1_000_000.0)
    use_case = FetchAccountUsage(
        usage_api, refresher, credentials, cache, clock, threshold=90.0, rng=HALF
    )
    return use_case, usage_api, refresher, credentials, cache, clock


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
        use_case, _, _, _, cache, _ = make_use_case(
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
        use_case, _, _, _, cache, _ = make_use_case(
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
        use_case, _, _, _, cache, _ = make_use_case(usage_api=FakeUsageApi(snapshot=maxed))

        use_case.execute("work", is_active=False)

        assert cache.load("work").poll_interval_s == poll_policy.EXHAUSTED_INTERVAL_S

    def test_an_exhausted_reset_caps_the_next_poll(self):
        # arrange — maxed and resetting sooner than EXHAUSTED_INTERVAL_S away
        clock = ControllableClock(now_epoch_s=1_000_000.0)
        reset_s = clock.now_epoch_s() + 90.0
        maxed = UsageSnapshot(
            five_hour=UsageWindow(pct=100.0, resets_at=_iso(reset_s)), seven_day=None, scoped=()
        )
        use_case, _, _, _, cache, _ = make_use_case(
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
        use_case, _, _, _, cache, _ = make_use_case(
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
        use_case, _, _, _, cache, _ = make_use_case(cache=cache, clock=clock)

        use_case.execute("work", is_active=False)

        assert cache.load("work").poll_interval_s == 450.0

    def test_last_429_at_s_survives_a_successful_fetch(self):
        # a success clears failure state, but never this stamp (claude-swap's
        # deliberate rule — cache_trust.recent_429 needs it to stay put)
        cache = InMemoryUsageCache()
        cache.save("work", replace(EMPTY_USAGE_CACHE_ENTRY, last_429_at_s=123.0))
        use_case, _, _, _, cache, _ = make_use_case(cache=cache)

        use_case.execute("work", is_active=False)

        assert cache.load("work").last_429_at_s == 123.0


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


_EXPIRED_MS = 1_000_000.0 * 1000.0 - 1_000.0  # well before now (1_000_000.0s)
_FRESH_MS = 1_000_000.0 * 1000.0 + 10_000_000.0  # well after now
_EXPIRED_CREDENTIAL = StoredOAuthCredential(
    access_token="at-old", refresh_token="rt-old", expires_at_ms=_EXPIRED_MS
)


def _refreshing_use_case(
    *, refresher: FakeTokenRefresher, credential: StoredOAuthCredential = _EXPIRED_CREDENTIAL
):
    return make_use_case(
        refresher=refresher, credentials=FakeCredentialStore(credentials={"work": credential})
    )


class TestRefreshBeforeFetch:
    """Inactive-account token refresh (ADR-0009): active accounts are never
    refreshed by this tool -- Claude Code owns those credentials."""

    def test_active_account_never_refreshes_even_when_expired(self):
        refresher = FakeTokenRefresher()
        use_case, usage_api, refresher, _, _, _ = _refreshing_use_case(refresher=refresher)

        use_case.execute("work", is_active=True)

        assert refresher.requests == []
        assert usage_api.requests == ["at-old"]

    def test_no_refresh_token_skips_refresh(self):
        refresher = FakeTokenRefresher()
        credential = replace(_EXPIRED_CREDENTIAL, refresh_token=None)
        use_case, usage_api, refresher, _, _, _ = _refreshing_use_case(
            refresher=refresher, credential=credential
        )

        use_case.execute("work", is_active=False)

        assert refresher.requests == []
        assert usage_api.requests == ["at-old"]

    def test_unexpired_token_skips_refresh(self):
        refresher = FakeTokenRefresher()
        credential = replace(_EXPIRED_CREDENTIAL, expires_at_ms=_FRESH_MS)
        use_case, usage_api, refresher, _, _, _ = _refreshing_use_case(
            refresher=refresher, credential=credential
        )

        use_case.execute("work", is_active=False)

        assert refresher.requests == []
        assert usage_api.requests == ["at-old"]

    def test_expiry_is_measured_in_milliseconds_not_seconds(self):
        # now=1_000_000.0s -> now_ms=1_000_000_000.0; a credential expiring
        # at 1_000_500_000.0ms is 500s out -- past the 300s skew, so NOT
        # expired. Pins the *1000.0 conversion itself (not just a huge
        # expired/fresh margin, which a x1000 vs x1001 slip can't fail).
        refresher = FakeTokenRefresher()
        credential = replace(_EXPIRED_CREDENTIAL, expires_at_ms=1_000_500_000.0)
        use_case, usage_api, refresher, _, _, _ = _refreshing_use_case(
            refresher=refresher, credential=credential
        )

        use_case.execute("work", is_active=False)

        assert refresher.requests == []
        assert usage_api.requests == ["at-old"]

    def test_expired_inactive_token_is_refreshed_before_fetching(self):
        refreshed = RefreshedTokens(
            access_token="at-new", refresh_token="rt-new", expires_in_s=3600.0
        )
        refresher = FakeTokenRefresher(refreshed=refreshed)
        use_case, usage_api, refresher, _, _, _ = _refreshing_use_case(refresher=refresher)

        use_case.execute("work", is_active=False)

        assert refresher.requests == ["rt-old"]
        assert usage_api.requests == ["at-new"]

    def test_refresh_persists_the_rotated_tokens(self):
        refreshed = RefreshedTokens(
            access_token="at-new", refresh_token="rt-new", expires_in_s=3600.0
        )
        refresher = FakeTokenRefresher(refreshed=refreshed)
        use_case, _, refresher, credentials, _, _ = _refreshing_use_case(refresher=refresher)

        use_case.execute("work", is_active=False)

        assert credentials.rotations == [
            ("work", "at-new", "rt-new", 1_000_000.0 * 1000.0 + 3_600_000.0)
        ]

    def test_refresh_keeps_the_old_refresh_token_when_not_rotated(self):
        refreshed = RefreshedTokens(access_token="at-new", refresh_token=None, expires_in_s=3600.0)
        refresher = FakeTokenRefresher(refreshed=refreshed)
        use_case, _, refresher, credentials, _, _ = _refreshing_use_case(refresher=refresher)

        use_case.execute("work", is_active=False)

        assert credentials.rotations[0][2] == "rt-old"

    def test_invalid_grant_is_permanent_and_never_hits_usage(self):
        cache = InMemoryUsageCache()
        cache.save("work", replace(EMPTY_USAGE_CACHE_ENTRY, last_good=_SNAPSHOT, fetched_at_s=0.0))
        refresher = FakeTokenRefresher(error=AnthropicApiError(400, "invalid_grant"))
        use_case, usage_api, refresher, credentials, cache, _ = make_use_case(
            refresher=refresher,
            credentials=FakeCredentialStore(credentials={"work": _EXPIRED_CREDENTIAL}),
            cache=cache,
        )

        report = use_case.execute("work", is_active=False)

        assert report == UsageReport(
            snapshot=_SNAPSHOT, stale=True, last_error="invalid_grant", permanent_auth_error=True
        )
        assert usage_api.requests == []

    def test_a_transient_refresh_failure_falls_through_with_the_old_token(self):
        refresher = FakeTokenRefresher(error=AnthropicApiError(500, None))
        use_case, usage_api, refresher, _, _, _ = _refreshing_use_case(refresher=refresher)

        report = use_case.execute("work", is_active=False)

        assert usage_api.requests == ["at-old"]
        assert report.snapshot == _SNAPSHOT

    def test_a_network_failure_during_refresh_falls_through(self):
        refresher = FakeTokenRefresher(error=HttpTransportError("timed out"))
        use_case, usage_api, refresher, _, _, _ = _refreshing_use_case(refresher=refresher)

        report = use_case.execute("work", is_active=False)

        assert usage_api.requests == ["at-old"]
        assert report.snapshot == _SNAPSHOT


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
