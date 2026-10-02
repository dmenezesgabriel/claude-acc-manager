"""UsageReport — what one usage-fetch attempt learned about an account."""

from typing import NamedTuple

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
