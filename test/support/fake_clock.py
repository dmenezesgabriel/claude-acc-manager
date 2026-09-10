"""Fixed-time ClockPort fake for hermetic tests."""

from claude_acc_manager.accounts.application.ports import ClockPort


class FakeClock(ClockPort):
    """Returns the same ISO-8601 string on every call."""

    def __init__(self, now_iso: str = "2026-09-10T12:00:00Z") -> None:
        """Pin the timestamp this clock reports."""
        self._now_iso = now_iso

    def now_iso(self) -> str:
        """The pinned timestamp."""
        return self._now_iso
