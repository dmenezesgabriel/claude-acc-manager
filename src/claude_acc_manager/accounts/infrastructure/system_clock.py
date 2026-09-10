"""ClockPort adapter over the system wall clock (UTC)."""

from datetime import UTC, datetime

from claude_acc_manager.accounts.application.ports import ClockPort


class SystemClock(ClockPort):
    """Reports the current UTC time as an ISO-8601 string with a ``Z`` suffix.

    Example:
        SystemClock().now_iso()  # "2026-09-10T12:00:00Z"
    """

    def now_iso(self) -> str:
        """Current UTC time, seconds precision, ``Z``-suffixed (not ``+00:00``)."""
        return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
