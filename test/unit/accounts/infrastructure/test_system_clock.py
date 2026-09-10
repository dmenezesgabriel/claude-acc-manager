"""Unit tests for accounts.infrastructure.system_clock."""

from datetime import UTC, datetime, timedelta

from claude_acc_manager.accounts.application.ports import ClockPort
from claude_acc_manager.accounts.infrastructure.system_clock import SystemClock


class TestSystemClockAdaptsThePort:
    """SystemClock explicitly subclasses the port (greppable map)."""

    def test_is_a_clock_port(self):
        # arrange / act / assert
        assert isinstance(SystemClock(), ClockPort)


class TestNowIso:
    """now_iso returns the current UTC time as an ISO-8601 Z-suffixed string."""

    def test_reports_a_time_within_the_call_window(self):
        # arrange
        before = datetime.now(UTC).replace(microsecond=0)

        # act
        timestamp = SystemClock().now_iso()

        # assert
        after = datetime.now(UTC)
        parsed = datetime.fromisoformat(timestamp)
        assert parsed.tzinfo == UTC
        assert before <= parsed <= after + timedelta(seconds=1)

    def test_uses_a_z_suffix_not_a_numeric_offset(self):
        # arrange / act
        timestamp = SystemClock().now_iso()

        # assert
        assert timestamp.endswith("Z")
        assert "+00:00" not in timestamp

    def test_has_seconds_precision_without_fractional_seconds(self):
        # arrange / act
        timestamp = SystemClock().now_iso()

        # assert
        assert "." not in timestamp
