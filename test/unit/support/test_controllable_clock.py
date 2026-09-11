"""Contract tests for the shared ControllableClock fake."""

from support.controllable_clock import ControllableClock

from claude_acc_manager.usage.application.ports import ClockPort


class TestControllableClockAdaptsThePort:
    def test_is_a_clock_port(self):
        assert isinstance(ControllableClock(), ClockPort)


class TestNowEpochS:
    def test_defaults_to_zero(self):
        assert ControllableClock().now_epoch_s() == 0.0

    def test_starts_at_the_given_time(self):
        assert ControllableClock(now_epoch_s=1_000.0).now_epoch_s() == 1_000.0


class TestAdvance:
    def test_moves_time_forward_by_the_given_seconds(self):
        clock = ControllableClock(now_epoch_s=1_000.0)
        clock.advance(50.0)
        assert clock.now_epoch_s() == 1_050.0

    def test_can_advance_more_than_once(self):
        clock = ControllableClock(now_epoch_s=0.0)
        clock.advance(10.0)
        clock.advance(5.0)
        assert clock.now_epoch_s() == 15.0
