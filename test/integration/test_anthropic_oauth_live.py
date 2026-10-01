"""Live smoke test for the Anthropic OAuth usage endpoint.

Opt-in only (``pytest -m integration``): hits the real, undocumented
``GET /api/oauth/usage`` with this machine's own Claude Code login and spends
one request from its usage budget. It exists to catch a wire-contract drift
that the fake-transport unit tests cannot see (docs/architecture.md §11: "the endpoint is
undocumented and can change") — the equivalent of ai-usagebar's ``make smoke``
and claude-swap's live tests.

Never prints the token or any response value — only asserts the parsed shape.
"""

import json
from pathlib import Path

import pytest

from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot
from claude_acc_manager.usage.infrastructure.anthropic_oauth import AnthropicUsageApi
from claude_acc_manager.usage.infrastructure.http_transport import UrllibHttpTransport

pytestmark = pytest.mark.integration


def _live_access_token() -> str:
    """The current OAuth access token from this machine's Claude Code login."""
    creds = Path.home() / ".claude" / ".credentials.json"
    if not creds.is_file():
        pytest.skip(f"no Claude Code login at {creds}")
    token = json.loads(creds.read_bytes()).get("claudeAiOauth", {}).get("accessToken")
    if not isinstance(token, str) or not token:
        pytest.skip("Claude Code login carries no access token")
    return token


class TestUsageEndpointWireContract:
    """The live response still parses into the shape this tool depends on."""

    def test_fetch_usage_returns_a_snapshot_with_the_five_hour_window(self):
        # arrange
        api = AnthropicUsageApi(UrllibHttpTransport())

        # act
        snapshot = api.fetch_usage(_live_access_token())

        # assert — five_hour is the window claude-swap/ai-usagebar both treat
        # as the presence check for a valid usage response
        assert isinstance(snapshot, UsageSnapshot)
        assert snapshot.five_hour is not None
        assert 0.0 <= snapshot.five_hour.pct <= 101.0
