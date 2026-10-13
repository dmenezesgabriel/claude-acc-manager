"""``FetchAccountUsage`` composition — refresh, contract gate, plan threading.

Before the API call the use case refreshes expiring credentials (inactive
accounts only — ADR-0009), checks the claude-version contract, and threads
every poll-plan factor through.
"""

from dataclasses import replace

import pytest
from support.controllable_clock import ControllableClock
from support.fake_claude_contract import FakeClaudeContractProbe
from support.fake_credential_store import FakeCredentialStore
from support.fake_token_refresher import FakeTokenRefresher
from support.fake_usage_api import FakeUsageApi
from support.fetch_usage_rig import EXPIRED_CREDENTIAL as _EXPIRED_CREDENTIAL
from support.fetch_usage_rig import FRESH_MS as _FRESH_MS
from support.fetch_usage_rig import SNAPSHOT as _SNAPSHOT
from support.fetch_usage_rig import iso as _iso
from support.fetch_usage_rig import make_use_case
from support.fetch_usage_rig import refreshing_use_case as _refreshing_use_case
from support.in_memory_usage_cache import InMemoryUsageCache

from claude_acc_manager.shared.claude_contract import (
    ClaudeContract,
    UnsupportedClaudeVersionError,
    contract_for_version,
)
from claude_acc_manager.usage.application.ports import (
    AnthropicApiError,
    HttpTransportError,
    RefreshedTokens,
)
from claude_acc_manager.usage.application.use_cases.fetch_account_usage import UsageReport
from claude_acc_manager.usage.domain.services import poll_policy
from claude_acc_manager.usage.domain.usage_cache_entry import EMPTY_USAGE_CACHE_ENTRY
from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot, UsageWindow


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
        # a success clears failure state, but never this stamp —
        # cache_trust.recent_429 needs it to stay put
        cache = InMemoryUsageCache()
        cache.save("work", replace(EMPTY_USAGE_CACHE_ENTRY, last_429_at_s=123.0))
        use_case, _, _, _, cache, _ = make_use_case(cache=cache)

        use_case.execute("work", is_active=False)

        assert cache.load("work").last_429_at_s == 123.0


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


class TestContractGate:
    """The refresh grant is the one-time-use act: the contract must hold
    before it runs — a refused probe consumes no token and persists
    nothing. Every path that never refreshes never probes."""

    def test_refused_contract_blocks_the_refresh_before_the_grant(self):
        # arrange — expired inactive credential + an out-of-band claude
        probe = FakeClaudeContractProbe(contract_for_version((2, 2, 0)))
        use_case, usage_api, refresher, credentials, _, _ = _refreshing_use_case(
            refresher=FakeTokenRefresher(), contract_probe=probe
        )

        # act / assert — refused before any POST, persist, or usage fetch
        with pytest.raises(UnsupportedClaudeVersionError, match="2.2.0"):
            use_case.execute("work", is_active=False)
        assert refresher.requests == []
        assert credentials.rotations == []
        assert usage_api.requests == []
        assert probe.probes == 1

    def test_below_band_refuses_naming_the_version(self):
        # arrange
        use_case, _, refresher, credentials, _, _ = _refreshing_use_case(
            refresher=FakeTokenRefresher(),
            contract_probe=FakeClaudeContractProbe(contract_for_version((2, 1, 143))),
        )

        # act / assert
        with pytest.raises(UnsupportedClaudeVersionError, match="2.1.143"):
            use_case.execute("work", is_active=False)
        assert refresher.requests == []
        assert credentials.rotations == []

    def test_undetermined_version_refuses(self):
        # arrange — no claude answered; still no token may be consumed
        use_case, _, refresher, credentials, _, _ = _refreshing_use_case(
            refresher=FakeTokenRefresher(),
            contract_probe=FakeClaudeContractProbe(contract_for_version(None)),
        )

        # act / assert
        with pytest.raises(UnsupportedClaudeVersionError, match="could not determine"):
            use_case.execute("work", is_active=False)
        assert refresher.requests == []
        assert credentials.rotations == []

    def test_an_assumed_contract_refreshes_normally(self):
        # arrange — the override-bypassed contract carries a supported verdict
        assumed = ClaudeContract(version=(2, 2, 0), supported=True, assumed=True, reason=None)
        refreshed = RefreshedTokens(
            access_token="at-new", refresh_token="rt-new", expires_in_s=3600.0
        )
        use_case, usage_api, refresher, credentials, _, _ = _refreshing_use_case(
            refresher=FakeTokenRefresher(refreshed=refreshed),
            contract_probe=FakeClaudeContractProbe(assumed),
        )

        # act
        use_case.execute("work", is_active=False)

        # assert
        assert refresher.requests == ["rt-old"]
        assert credentials.rotations != []
        assert usage_api.requests == ["at-new"]

    def test_an_unexpired_token_never_probes(self):
        # arrange — expired-looking setup but a live token: pure read path
        probe = FakeClaudeContractProbe(contract_for_version(None))
        credential = replace(_EXPIRED_CREDENTIAL, expires_at_ms=_FRESH_MS)
        use_case, usage_api, refresher, _, _, _ = _refreshing_use_case(
            refresher=FakeTokenRefresher(), credential=credential, contract_probe=probe
        )

        # act
        use_case.execute("work", is_active=False)

        # assert
        assert usage_api.requests == ["at-old"]
        assert refresher.requests == []
        assert probe.probes == 0

    def test_an_active_account_never_probes(self):
        # arrange — claude owns the active tokens; no refresh means no gate
        probe = FakeClaudeContractProbe(contract_for_version(None))
        use_case, usage_api, refresher, _, _, _ = _refreshing_use_case(
            refresher=FakeTokenRefresher(), contract_probe=probe
        )

        # act
        use_case.execute("work", is_active=True)

        # assert
        assert usage_api.requests == ["at-old"]
        assert refresher.requests == []
        assert probe.probes == 0

    def test_a_cache_serve_never_probes(self):
        # arrange — a fresh entry settles the call before the credential read
        probe = FakeClaudeContractProbe(contract_for_version(None))
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(EMPTY_USAGE_CACHE_ENTRY, last_good=_SNAPSHOT, fetched_at_s=1_000_000.0 - 10.0),
        )
        use_case, _, _, _, _, _ = make_use_case(cache=cache, contract_probe=probe)

        # act
        use_case.execute("work", is_active=False)

        # assert
        assert probe.probes == 0
