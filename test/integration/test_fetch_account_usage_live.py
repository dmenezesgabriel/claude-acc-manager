"""Live smoke test for the FetchAccountUsage use case end to end.

Opt-in only (``pytest -m integration``): drives the real use case — real
usage-endpoint fetch, real FileUsageCache write to a tmp store, real
poll-cadence planning — against this machine's own Claude Code login. Never
prints the token or any response value.

Safety: always calls ``execute(..., is_active=True)``, so
``FetchAccountUsage`` never attempts a refresh (ADR-0009: an active
account's tokens are Claude Code's own) — the refresher and the
persist-rotation path are provably unreachable, enforced here by fakes that
raise if either is ever called.
"""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from claude_acc_manager.usage.application.ports import (
    CredentialStorePort,
    RefreshedTokens,
    TokenRefresherPort,
)
from claude_acc_manager.usage.application.use_cases.fetch_account_usage import FetchAccountUsage
from claude_acc_manager.usage.domain.oauth_credential import (
    StoredOAuthCredential,
    stored_credential_from_claude_ai_oauth,
)
from claude_acc_manager.usage.infrastructure.anthropic_oauth import AnthropicUsageApi
from claude_acc_manager.usage.infrastructure.file_usage_cache import FileUsageCache
from claude_acc_manager.usage.infrastructure.http_transport import UrllibHttpTransport
from claude_acc_manager.usage.infrastructure.system_clock import SystemClock

pytestmark = pytest.mark.integration


class _UnreachableCredentialStore(CredentialStorePort):
    """Wraps the live credential; read-only — persist_rotation must never run.

    Safe by construction: execute(..., is_active=True) never refreshes
    (ADR-0009), so this path is provably unreachable in this test.
    """

    def __init__(self, credential: StoredOAuthCredential) -> None:
        self._credential = credential

    def read(self, account_key: str) -> StoredOAuthCredential | None:
        return self._credential

    def persist_rotation(
        self, account_key: str, access_token: str, refresh_token: str, expires_at_ms: float
    ) -> None:
        raise AssertionError("must never rotate the live login's tokens")


class _UnreachableRefresher(TokenRefresherPort):
    """A refresher that must never run — same is_active=True guarantee."""

    def refresh(self, refresh_token: str) -> RefreshedTokens:
        raise AssertionError("must never refresh an is_active account")


def _live_credential() -> StoredOAuthCredential:
    """The current stored OAuth credential from this machine's Claude Code login."""
    path = Path.home() / ".claude" / ".credentials.json"
    if not path.is_file():
        pytest.skip(f"no Claude Code login at {path}")
    oauth = json.loads(path.read_bytes()).get("claudeAiOauth")
    if not isinstance(oauth, Mapping):
        pytest.skip("credentials file carries no claudeAiOauth block")
    credential = stored_credential_from_claude_ai_oauth(cast("Mapping[str, object]", oauth))
    if credential is None:
        pytest.skip("Claude Code login carries no usable access token")
    return credential


class TestFetchAccountUsageLive:
    """The full use case — fetch, cache, plan — against the real endpoint."""

    def test_execute_fetches_and_caches_a_live_snapshot(self, tmp_path: Path):
        # arrange
        cache = FileUsageCache(tmp_path)
        use_case = FetchAccountUsage(
            AnthropicUsageApi(UrllibHttpTransport()),
            _UnreachableRefresher(),
            _UnreachableCredentialStore(_live_credential()),
            cache,
            SystemClock(),
        )

        # act
        report = use_case.execute("live", is_active=True)

        # assert
        assert report.snapshot is not None
        assert report.last_error is None
        assert not report.permanent_auth_error
        assert cache.load("live").last_good == report.snapshot
