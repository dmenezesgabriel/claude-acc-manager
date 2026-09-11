"""ClockPort adapter over the system wall clock."""

import time

from claude_acc_manager.usage.application.ports import ClockPort


class SystemClock(ClockPort):
    """Reports the current time as Unix epoch seconds.

    Example:
        SystemClock().now_epoch_s()  # 1757548800.0
    """

    def now_epoch_s(self) -> float:
        """Current time as Unix epoch seconds."""
        return time.time()
