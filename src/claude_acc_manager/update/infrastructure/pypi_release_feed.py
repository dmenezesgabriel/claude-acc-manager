"""PyPiReleaseFeed — ReleaseFeedPort over PyPI's JSON package API.

``https://pypi.org/pypi/claude-acc-manager/json`` is the single release
source (PSR publishes there and nowhere else — per-method registries buy
nothing, unlike opencode). The check is advisory: every failure — a
non-2xx status, a transport error, a body that is not a JSON object with
a non-empty ``info.version`` — returns ``None`` so a dead index can never
break the command that triggered the check (port contract).

No allowlist guard (usage.infrastructure.anthropic_oauth carries one):
the URL is a hardcoded constant and the GET carries no credentials —
unlike the Anthropic adapter, there is no bearer token a bad URL could
leak. The 2s budget keeps a dead network from stalling a command the
user is waiting on.

Example:
    feed = PyPiReleaseFeed(UrllibHttpTransport())
    latest = feed.latest_version()  # "1.2.0", or None on any failure
"""

import json
from typing import cast

from claude_acc_manager import package_version
from claude_acc_manager.update.application.ports import HttpGetPort, ReleaseFeedPort
from claude_acc_manager.usage.application.ports import HttpTransportError

PYPI_URL = "https://pypi.org/pypi/claude-acc-manager/json"

# Honest identifier (ADR-0007): the running version, so index logs show
# which releases poll — package_version() rather than a second literal to
# keep bumped.
_HEADERS = {"User-Agent": f"claude-acc-manager/{package_version()}"}
_TIMEOUT_S = 2.0


def _latest_from_document(document: object) -> str | None:
    """The ``info.version`` string of a parsed PyPI JSON document, or None.

    cast() is a runtime no-op — its type argument is consumed by type
    checkers only, so mutants of it are equivalent by construction (same
    reason usage/infrastructure/anthropic_oauth.py carries this pragma).
    """
    if not isinstance(document, dict):
        return None
    info = cast("dict[str, object]", document).get("info")  # pragma: no mutate
    if not isinstance(info, dict):
        return None
    version = cast("dict[str, object]", info).get("version")  # pragma: no mutate
    if not isinstance(version, str) or not version.strip():
        return None
    return version


class PyPiReleaseFeed(ReleaseFeedPort):
    """ReleaseFeedPort over PyPI's JSON API — one GET, never raises.

    Example:
        PyPiReleaseFeed(UrllibHttpTransport()).latest_version()
    """

    def __init__(self, http: HttpGetPort) -> None:
        """Inject the HTTP transport (test seam: FakeHttpTransport)."""
        self._http = http

    def latest_version(self) -> str | None:
        """The newest published release string, or None on any failure (port contract)."""
        try:
            response = self._http.request("GET", PYPI_URL, _HEADERS, None, timeout_s=_TIMEOUT_S)
        except HttpTransportError:
            return None
        if response.status // 100 != 2:
            return None
        try:
            document: object = json.loads(response.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        return _latest_from_document(document)
