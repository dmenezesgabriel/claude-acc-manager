"""Unit tests for usage.infrastructure.system_clock."""

import time

from claude_acc_manager.usage.application.ports import ClockPort
from claude_acc_manager.usage.infrastructure.system_clock import SystemClock


class TestSystemClockAdaptsThePort:
    """SystemClock explicitly subclasses the port (greppable map)."""

    def test_is_a_clock_port(self):
        assert isinstance(SystemClock(), ClockPort)


class TestNowEpochS:
    def test_reports_a_time_within_the_call_window(self):
        # arrange
        before = time.time()

        # act
        now = SystemClock().now_epoch_s()

        # assert
        after = time.time()
        assert before <= now <= after
