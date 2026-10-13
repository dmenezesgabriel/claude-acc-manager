"""Shared builders for the ``FetchAccountUsage`` use-case tests.

``make_use_case`` wires the real use case to named fakes at every port and
returns the collaborators so tests can assert on calls; the module-level
credentials/snapshots are the canonical fixtures each scenario varies with
``dataclasses.replace``.
"""

from datetime import UTC, datetime

from claude_acc_manager.shared.claude_contract import contract_for_version
from claude_acc_manager.usage.application.use_cases.fetch_account_usage import (
    FetchAccountUsage,
)
from claude_acc_manager.usage.domain.oauth_credential import StoredOAuthCredential
from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot, UsageWindow
from support.controllable_clock import ControllableClock
from support.fake_claude_contract import FakeClaudeContractProbe
from support.fake_credential_store import FakeCredentialStore
from support.fake_token_refresher import FakeTokenRefresher
from support.fake_usage_api import FakeUsageApi
from support.in_memory_usage_cache import InMemoryUsageCache

SNAPSHOT = UsageSnapshot(five_hour=UsageWindow(pct=10.0, resets_at=None), seven_day=None, scoped=())
CREDENTIAL = StoredOAuthCredential(access_token="at-1", refresh_token="rt-1", expires_at_ms=None)
HALF = lambda: 0.5  # noqa: E731 — jitter factor exactly 1.0

EXPIRED_MS = 1_000_000.0 * 1000.0 - 1_000.0  # well before now (1_000_000.0s)
FRESH_MS = 1_000_000.0 * 1000.0 + 10_000_000.0  # well after now
EXPIRED_CREDENTIAL = StoredOAuthCredential(
    access_token="at-old", refresh_token="rt-old", expires_at_ms=EXPIRED_MS
)


def iso(epoch_s: float) -> str:
    """Format an epoch second as the ISO-8601 string the cache stores."""
    return datetime.fromtimestamp(epoch_s, tz=UTC).isoformat().replace("+00:00", "Z")


def make_use_case(
    *,
    usage_api: FakeUsageApi | None = None,
    refresher: FakeTokenRefresher | None = None,
    credentials: FakeCredentialStore | None = None,
    cache: InMemoryUsageCache | None = None,
    clock: ControllableClock | None = None,
    contract_probe: FakeClaudeContractProbe | None = None,
) -> tuple[
    FetchAccountUsage,
    FakeUsageApi,
    FakeTokenRefresher,
    FakeCredentialStore,
    InMemoryUsageCache,
    ControllableClock,
]:
    """Wire ``FetchAccountUsage`` to fakes; unset collaborators get defaults."""
    usage_api = usage_api or FakeUsageApi(snapshot=SNAPSHOT)
    refresher = refresher or FakeTokenRefresher()
    credentials = credentials or FakeCredentialStore(credentials={"work": CREDENTIAL})
    cache = cache or InMemoryUsageCache()
    clock = clock or ControllableClock(now_epoch_s=1_000_000.0)
    use_case = FetchAccountUsage(
        usage_api,
        refresher,
        credentials,
        cache,
        clock,
        contract_probe or FakeClaudeContractProbe(contract_for_version((2, 1, 288))),
        threshold=90.0,
        rng=HALF,
    )
    return use_case, usage_api, refresher, credentials, cache, clock


def refreshing_use_case(
    *,
    refresher: FakeTokenRefresher,
    credential: StoredOAuthCredential = EXPIRED_CREDENTIAL,
    contract_probe: FakeClaudeContractProbe | None = None,
):
    """``make_use_case`` preset: the stored credential needs a refresh first."""
    return make_use_case(
        refresher=refresher,
        credentials=FakeCredentialStore(credentials={"work": credential}),
        contract_probe=contract_probe,
    )
