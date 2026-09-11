"""Fetch one account's usage, serving cache first and planning the next poll."""

import random
from collections.abc import Callable
from dataclasses import replace
from typing import NamedTuple

from claude_acc_manager.usage.application.ports import (
    ClockPort,
    CredentialStorePort,
    UsageApiPort,
    UsageCachePort,
)
from claude_acc_manager.usage.domain.services import cache_trust, poll_policy
from claude_acc_manager.usage.domain.services.headroom import account_headroom
from claude_acc_manager.usage.domain.usage_cache_entry import (
    EMPTY_USAGE_CACHE_ENTRY,
    UsageCacheEntry,
)
from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot


class UsageReport(NamedTuple):
    """What one ``execute()`` call learned about an account's usage.

    ``snapshot`` is ``None`` only when nothing trustworthy is known at all.
    ``stale`` is True when *snapshot* is served last-good data, not a fresh
    fetch. ``last_error`` names the reason a fresh fetch didn't happen or
    didn't succeed (e.g. ``"no-credential"``); ``None`` on a fresh success.

    Example:
        UsageReport(snapshot, stale=False, last_error=None, permanent_auth_error=False)
    """

    snapshot: UsageSnapshot | None
    stale: bool
    last_error: str | None
    permanent_auth_error: bool


class FetchAccountUsage:
    """Serve a fresh usage snapshot from cache, or fetch and cache one.

    Example:
        FetchAccountUsage(usage_api, credentials, cache, clock).execute("work", is_active=True)
    """

    def __init__(
        self,
        usage_api: UsageApiPort,
        credentials: CredentialStorePort,
        cache: UsageCachePort,
        clock: ClockPort,
        *,
        rng: Callable[[], float] = random.random,
    ) -> None:
        """Store the injected ports; *rng* seeds poll-cadence jitter (tests pin it)."""
        self._usage_api = usage_api
        self._credentials = credentials
        self._cache = cache
        self._clock = clock
        self._rng = rng

    def execute(self, account_key: str, is_active: bool) -> UsageReport:
        """Return the account's usage, fetching when the cache is stale.

        Example:
            report = use_case.execute("work", is_active=True)
        """
        now = self._clock.now_epoch_s()
        entry = self._cache.load(account_key)
        if (
            cache_trust.is_fresh(entry, now, poll_policy.SERVE_TTL_S)
            and entry.last_good is not None
        ):
            return UsageReport(
                entry.last_good, stale=False, last_error=None, permanent_auth_error=False
            )

        credential = self._credentials.read(account_key)
        if credential is None:
            return UsageReport(
                entry.last_good,
                stale=entry.last_good is not None,
                last_error="no-credential",
                permanent_auth_error=False,
            )

        snapshot = self._usage_api.fetch_usage(credential.access_token)
        new_entry = self._plan_success(entry, snapshot, is_active, now)
        self._cache.save(account_key, new_entry)
        return UsageReport(snapshot, stale=False, last_error=None, permanent_auth_error=False)

    def _plan_success(
        self, entry: UsageCacheEntry, snapshot: UsageSnapshot, is_active: bool, now: float
    ) -> UsageCacheEntry:
        """The cache entry to save after a fresh, successful fetch."""
        headroom = account_headroom(snapshot)
        next_poll_at, interval = poll_policy.plan_after_fetch(
            prev_interval_s=entry.poll_interval_s,
            prev_pct=poll_policy.binding_pct(entry.last_good),
            new_pct=poll_policy.binding_pct(snapshot),
            is_active=is_active,
            headroom=headroom,
            limiting_reset_s=poll_policy.limiting_reset_epoch(snapshot),
            earliest_reset_s=poll_policy.earliest_future_reset_epoch(snapshot, now),
            recent_429=cache_trust.recent_429(entry, now, poll_policy.RECENT_429_WINDOW_S),
            now_s=now,
            rng=self._rng,
        )
        return replace(
            EMPTY_USAGE_CACHE_ENTRY,
            last_good=snapshot,
            fetched_at_s=now,
            last_429_at_s=entry.last_429_at_s,
            next_poll_at_s=next_poll_at,
            poll_interval_s=interval,
        )
