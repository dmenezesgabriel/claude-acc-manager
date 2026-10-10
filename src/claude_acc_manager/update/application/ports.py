"""Ports of the update component — the single map of every boundary."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from claude_acc_manager.usage.application.ports import HttpTransportPort


@runtime_checkable
class HttpGetPort(HttpTransportPort, Protocol):
    """Boundary over the HTTP client update talks to PyPI through.

    Structurally identical to ``usage``'s ``HttpTransportPort`` — same
    ``request()`` signature — so the shared ``UrllibHttpTransport`` adapter
    and the ``FakeHttpTransport`` fake satisfy it unchanged. The narrower
    name records that update performs GETs only, and keeps every boundary
    this component drives discoverable in one file (AGENTS.md).

    Example:
        response = http.request("GET", url, headers, None, timeout_s=2.0)
    """


@runtime_checkable
class ReleaseFeedPort(Protocol):
    """Boundary for asking the package index what the newest cam release is.

    Advisory and fail-open by contract, like ``usage``'s
    ``IdentityLookupPort``: every failure — a non-2xx status, a transport
    error, or a malformed body — returns ``None`` and never raises, so the
    check can never break the command that triggered it.

    Example:
        latest = feed.latest_version()  # "1.2.0", or None on any failure
    """

    def latest_version(self) -> str | None:
        """The newest published release string, or None on any failure."""
        ...


@dataclass(frozen=True)
class UpdateCheckRecord:
    """One cached check outcome: when it ran and what the index reported.

    ``latest_version`` is ``None`` when the check itself failed — the
    failure is cached too, so a dead index suppresses re-checks for the
    TTL instead of being retried on every command (the failure-caching
    rule the notice's budget rests on).

    Example:
        UpdateCheckRecord(checked_at_s=1_760_000_000.0, latest_version="1.2.0")
    """

    checked_at_s: float
    latest_version: str | None


@runtime_checkable
class UpdateCheckCachePort(Protocol):
    """Persistence boundary for the single last-check record.

    ``load`` returning ``None`` means no check has ever run; a record
    whose ``latest_version`` is ``None`` means one ran and failed. The
    distinction drives the freshness gate — only the former fetches.

    Example:
        record = cache.load()
        if record is None or now - record.checked_at_s > TTL_S:
            cache.save(UpdateCheckRecord(now, feed.latest_version()))
    """

    def load(self) -> UpdateCheckRecord | None:
        """The last check record, or None when no check has ever run."""
        ...

    def save(self, record: UpdateCheckRecord) -> None:
        """Replace the last-check record."""
        ...


class UpgradeToolMissingError(Exception):
    """The detected package manager's executable is not on PATH.

    Replaces a raw ``FileNotFoundError`` at the port boundary so the use
    case can report the tool by name instead of surfacing an OS error.
    """


@runtime_checkable
class UpgradeRunnerPort(Protocol):
    """Boundary for executing the package manager's upgrade command.

    The use case owns the per-manager argv (T5 policy); the runner only
    executes it verbatim — inheriting the terminal so uv/pipx progress
    reaches the user, with no timeout since upgrades legitimately take
    minutes.

    Example:
        rc = runner.run(["uv", "tool", "upgrade", "claude-acc-manager"])
    """

    def run(self, argv: Sequence[str]) -> int:
        """Run *argv* (non-empty) and return its exit code.

        Raises UpgradeToolMissingError when ``argv[0]`` is not on PATH.
        """
        ...
