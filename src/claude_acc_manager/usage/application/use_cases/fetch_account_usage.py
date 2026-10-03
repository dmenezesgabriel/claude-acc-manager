"""Fetch one account's usage, serving cache first and planning the next poll."""

import random
from collections.abc import Callable
from dataclasses import replace

from claude_acc_manager.usage.application.ports import (
    AnthropicApiError,
    ClaudeContractPort,
    ClockPort,
    CredentialStorePort,
    HttpTransportError,
    TokenRefresherPort,
    UsageApiPort,
    UsageCachePort,
)
from claude_acc_manager.usage.domain.oauth_credential import StoredOAuthCredential, token_expired
from claude_acc_manager.usage.domain.services import cache_trust, poll_policy
from claude_acc_manager.usage.domain.services.headroom import account_headroom
from claude_acc_manager.usage.domain.usage_cache_entry import (
    EMPTY_USAGE_CACHE_ENTRY,
    UsageCacheEntry,
)
from claude_acc_manager.usage.domain.usage_report import UsageReport
from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot

__all__ = ["FetchAccountUsage", "UsageReport"]


class FetchAccountUsage:
    """Serve a fresh usage snapshot from cache, or fetch and cache one.

    Example:
        FetchAccountUsage(usage_api, refresher, credentials, cache, clock, probe).execute(
            "work", is_active=True
        )
    """

    def __init__(
        self,
        usage_api: UsageApiPort,
        refresher: TokenRefresherPort,
        credentials: CredentialStorePort,
        cache: UsageCachePort,
        clock: ClockPort,
        claude_contract: ClaudeContractPort,
        *,
        threshold: float,
        rng: Callable[[], float] = random.random,
    ) -> None:
        """Store the injected ports; *rng* seeds poll-cadence jitter (tests pin it).

        *threshold* is the autoswitch switch-threshold the urgent cadence
        escalates inside — injected from settings so every surface plans
        consistently; a caller may still override per call.
        """
        self._usage_api = usage_api
        self._refresher = refresher
        self._credentials = credentials
        self._cache = cache
        self._clock = clock
        self._claude_contract = claude_contract
        self._threshold = threshold
        self._rng = rng

    def execute(
        self,
        account_key: str,
        is_active: bool,
        *,
        force: bool = False,
        threshold: float | None = None,
    ) -> UsageReport:
        """Return the account's usage, fetching when the cache is stale.

        ``force`` skips the freshness/serve and not-yet-due gates (the
        engine's escalated refresh) but never the armed 429 backoff.
        ``threshold`` overrides the constructor value for this call.

        Example:
            report = use_case.execute("work", is_active=True, force=True)
        """
        now = self._clock.now_epoch_s()
        entry = self._cache.load(account_key)
        held = self._serve_without_fetch(entry, now, force)
        if held is not None:
            return held

        credential = self._credentials.read(account_key)
        if credential is None:
            return UsageReport(
                entry.last_good,
                stale=entry.last_good is not None,
                last_error="no-credential",
                permanent_auth_error=False,
            )

        access_token, permanent_error = self._resolve_access_token(
            account_key, credential, is_active, now
        )
        if permanent_error is not None:
            return UsageReport(
                entry.last_good,
                stale=entry.last_good is not None,
                last_error=permanent_error,
                permanent_auth_error=True,
            )

        try:
            snapshot = self._usage_api.fetch_usage(access_token)
        except AnthropicApiError as exc:
            return self._handle_fetch_failure(account_key, entry, now, f"http-{exc.status}")
        except HttpTransportError:
            return self._handle_fetch_failure(account_key, entry, now, "network")

        new_entry = self._plan_success(
            entry, snapshot, is_active, now, self._threshold if threshold is None else threshold
        )
        self._cache.save(account_key, new_entry)
        return UsageReport(snapshot, stale=False, last_error=None, permanent_auth_error=False)

    def _serve_without_fetch(
        self, entry: UsageCacheEntry, now: float, force: bool
    ) -> UsageReport | None:
        """A report when the cache settles the call without fetching, else None.

        Fresh last-good data is served as-is; a live hold (armed backoff, or
        a future plan deadline when not ``force``) serves the frozen entry.
        """
        if (
            not force
            and cache_trust.is_fresh(entry, now, poll_policy.SERVE_TTL_S)
            and entry.last_good is not None
        ):
            return UsageReport(
                entry.last_good, stale=False, last_error=None, permanent_auth_error=False
            )
        hold = self._hold_reason(entry, now, force=force)
        if hold is not None:
            return self._frozen_report(entry, now, entry.last_error or hold)
        return None

    def _handle_fetch_failure(
        self, account_key: str, entry: UsageCacheEntry, now: float, last_error: str
    ) -> UsageReport:
        """Freeze last-good, record the failure, and serve it if still trusted.

        A 429 (the only ``last_error`` this arms the flat backoff for) is a
        polling throttle, not a change in the account's real quota
        (docs/architecture.md §11): it arms the backoff and stamps ``last_429_at_s``
        (cache_trust.recent_429), but never clears ``last_good`` — usage
        only rises within a window, so frozen data is a valid lower bound
        until it's no longer trustworthy (cache_trust.trust_ok).
        """
        is_429 = last_error == "http-429"
        new_entry = replace(
            entry,
            consecutive_failures=entry.consecutive_failures + 1,
            last_error=last_error,
            backoff_until_s=now + poll_policy.RATE_LIMIT_BACKOFF_S
            if is_429
            else entry.backoff_until_s,
            last_429_at_s=now if is_429 else entry.last_429_at_s,
        )
        self._cache.save(account_key, new_entry)
        return self._frozen_report(new_entry, now, last_error)

    @staticmethod
    def _hold_reason(entry: UsageCacheEntry, now: float, force: bool) -> str | None:
        """Why a stale entry must not fetch right now, or None when it may.

        The backoff a 429 armed is a live hold and is checked before the
        plan's own deadline — a future ``next_poll_at_s`` alone is just
        scheduling, and ``force`` skips it (escalated refresh), never the
        backoff.
        """
        if cache_trust.in_backoff(entry, now):
            return "backoff"
        if not force and not poll_policy.poll_due(entry.next_poll_at_s, now):
            return "not-due"
        return None

    @staticmethod
    def _frozen_report(entry: UsageCacheEntry, now: float, last_error: str) -> UsageReport:
        """Serve the frozen last_good while trusted, else report unknown.

        Shared by the no-fetch gate (a skipped attempt is not a failure —
        the entry is untouched) and by a real fetch failure (the failed
        attempt is already recorded on the entry handed in).
        """
        earliest_reset = poll_policy.earliest_reset_epoch(entry.last_good)
        if cache_trust.trust_ok(entry, now, earliest_reset, poll_policy.TRUST_MAX_AGE_S):
            return UsageReport(
                entry.last_good, stale=True, last_error=last_error, permanent_auth_error=False
            )
        return UsageReport(None, stale=False, last_error=last_error, permanent_auth_error=False)

    def _resolve_access_token(
        self, account_key: str, credential: StoredOAuthCredential, is_active: bool, now: float
    ) -> tuple[str, str | None]:
        """``(access_token, permanent_error)``.

        Refreshes an expired inactive token first (ADR-0009: the active
        account's tokens are Claude Code's own — this tool never refreshes
        them). ``invalid_grant`` is the one refresh failure that stops the
        whole fetch (the lineage is provably dead); any other refresh
        failure is transient and falls through with the existing token,
        letting the usage endpoint's own error surface normally.
        """
        if is_active or not credential.refresh_token:
            return credential.access_token, None
        if not token_expired(credential.expires_at_ms, now * 1000.0):
            return credential.access_token, None
        # The grant consumes the one-time-use refresh token — refuse before
        # it runs when the credential contract can't be verified, rather
        # than rotating a lineage the persist may not survive under.
        self._claude_contract.probe().require_supported()
        try:
            refreshed = self._refresher.refresh(credential.refresh_token)
        except AnthropicApiError as exc:
            if exc.error_code == "invalid_grant":
                return credential.access_token, "invalid_grant"
            return credential.access_token, None
        except HttpTransportError:
            return credential.access_token, None
        self._credentials.persist_rotation(
            account_key,
            refreshed.access_token,
            refreshed.refresh_token or credential.refresh_token,
            now * 1000.0 + refreshed.expires_in_s * 1000.0,
        )
        return refreshed.access_token, None

    def _plan_success(
        self,
        entry: UsageCacheEntry,
        snapshot: UsageSnapshot,
        is_active: bool,
        now: float,
        threshold: float,
    ) -> UsageCacheEntry:
        """The cache entry to save after a fresh, successful fetch."""
        headroom = account_headroom(snapshot)
        next_poll_at, interval = poll_policy.plan_after_fetch(
            prev_interval_s=entry.poll_interval_s,
            prev_pct=poll_policy.binding_pct(entry.last_good),
            new_pct=poll_policy.binding_pct(snapshot),
            is_active=is_active,
            threshold=threshold,
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
