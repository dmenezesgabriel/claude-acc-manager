"""Advanceable ClockPort fake for hermetic cache/cadence tests.

Unlike accounts' FakeClock (a fixed ISO-8601 string), poll-cadence and
cache-trust tests need to move time forward within a single test.
"""

from claude_acc_manager.usage.application.ports import ClockPort


class ControllableClock(ClockPort):
    """Reports a pinned epoch time that ``advance()`` moves forward."""

    def __init__(self, now_epoch_s: float = 0.0) -> None:
        """Start the clock at *now_epoch_s*."""
        self._now_epoch_s = now_epoch_s

    def now_epoch_s(self) -> float:
        """The current pinned time."""
        return self._now_epoch_s

    def advance(self, seconds: float) -> None:
        """Move the clock forward by *seconds*."""
        self._now_epoch_s += seconds
