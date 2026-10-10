"""Compact human durations for the TUI status line."""

import time
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from support.use_cases import make_account

from claude_acc_manager.tui.formatting import (
    clock_stamp,
    email_fragment,
    format_age,
    format_duration,
    reset_clock,
    reset_text,
)
from claude_acc_manager.usage.domain.services.poll_policy import SERVE_TTL_S
from claude_acc_manager.usage.domain.usage_snapshot import UsageWindow


def _local(hour: int, minute: int = 0, *, day: int = 23) -> float:
    """Epoch seconds for a wall-clock reading on a fixed local day."""
    return datetime(2026, 5, day, hour, minute).timestamp()


def _iso(epoch_s: float) -> str:
    """The ``resets_at`` wire shape for a known epoch."""
    return datetime.fromtimestamp(epoch_s, tz=UTC).isoformat()


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0s"),
        (45, "45s"),
        (59.9, "59s"),
        (60, "1m"),
        (599, "9m"),
        (3600, "1h"),
        (7980, "2h 13m"),
        (86400, "1d"),
        (273600, "3d 4h"),
    ],
)
def test_format_duration(seconds: float, expected: str) -> None:
    """Whole-unit durations: s below a minute, m below an hour, then h+d."""
    assert format_duration(seconds) == expected


class TestResetText:
    """Live countdown to a window's reset, recomputed at render time."""

    def test_no_window_means_no_countdown(self) -> None:
        assert reset_text(None, _local(12)) is None

    def test_a_window_without_resets_at_means_no_countdown(self) -> None:
        assert reset_text(UsageWindow(pct=40.0, resets_at=None), _local(12)) is None

    def test_a_malformed_resets_at_means_no_countdown(self) -> None:
        assert reset_text(UsageWindow(pct=40.0, resets_at="soon"), _local(12)) is None

    def test_a_past_reset_reads_now(self) -> None:
        window = UsageWindow(pct=40.0, resets_at=_iso(_local(11)))
        assert reset_text(window, _local(12)) == "resets now"

    def test_a_reset_at_exactly_now_reads_now(self) -> None:
        now = _local(12)
        window = UsageWindow(pct=40.0, resets_at=_iso(now))
        assert reset_text(window, now) == "resets now"

    def test_a_subsecond_future_reset_counts_down(self) -> None:
        now = _local(12)
        window = UsageWindow(pct=40.0, resets_at=_iso(now + 0.5))
        assert reset_text(window, now) == "resets 0s"

    def test_a_future_reset_reads_as_a_countdown(self) -> None:
        now = _local(12)
        window = UsageWindow(pct=40.0, resets_at=_iso(now + 7980))
        assert reset_text(window, now) == "resets 2h 13m"

    def test_the_z_suffix_is_accepted(self) -> None:
        # the wire shape — the API stamps resets_at with a literal Z
        window = UsageWindow(pct=40.0, resets_at="2199-05-23T20:39:00Z")
        assert reset_text(window, _local(12)) is not None
        assert reset_clock(window, _local(12)) is not None


class TestResetClock:
    """Absolute local reset time: HH:MM same-day, else 'Mon D HH:MM'."""

    def test_no_window_means_no_clock(self) -> None:
        assert reset_clock(None, _local(12)) is None

    def test_a_malformed_resets_at_means_no_clock(self) -> None:
        assert reset_clock(UsageWindow(pct=40.0, resets_at="soon"), _local(12)) is None

    def test_a_past_reset_means_no_clock(self) -> None:
        window = UsageWindow(pct=40.0, resets_at=_iso(_local(11)))
        assert reset_clock(window, _local(12)) is None

    def test_a_reset_at_exactly_now_means_no_clock(self) -> None:
        now = _local(12)
        window = UsageWindow(pct=40.0, resets_at=_iso(now))
        assert reset_clock(window, now) is None

    def test_a_same_day_reset_reads_hh_mm(self) -> None:
        window = UsageWindow(pct=40.0, resets_at=_iso(_local(20, 39)))
        assert reset_clock(window, _local(12)) == "20:39"

    def test_another_day_reads_month_day_hh_mm(self) -> None:
        window = UsageWindow(pct=40.0, resets_at=_iso(_local(8, 59, day=24)))
        assert reset_clock(window, _local(12)) == "May 24 08:59"


class TestFormatAge:
    """The staleness note hides while a measurement is comfortably fresh."""

    def test_no_age_means_no_note(self) -> None:
        assert format_age(None) is None

    def test_fresh_measurements_hide_the_note(self) -> None:
        assert format_age(SERVE_TTL_S - 1) is None

    def test_the_ttl_floor_is_inclusive(self) -> None:
        assert format_age(SERVE_TTL_S) == "· 3m ago"

    def test_stale_measurements_read_as_ago(self) -> None:
        assert format_age(7200) == "· 2h ago"


class TestClockStamp:
    """HH:MM:SS local-time stamps for the event log."""

    def test_the_stamp_is_local_hh_mm_ss(self) -> None:
        now = _local(20, 39) + 42
        assert clock_stamp(now) == time.strftime("%H:%M:%S", time.localtime(now))


class TestEmailFragment:
    """The privacy join — redaction omits the address, not part of it."""

    def test_redacted_renders_nothing(self) -> None:
        assert email_fragment(make_account("work"), redact=True) == ""

    def test_visible_wraps_the_address_in_parens(self) -> None:
        assert email_fragment(make_account("work"), redact=False) == " (work@example.com)"

    def test_an_absent_email_renders_nothing_either_way(self) -> None:
        account = make_account("work")
        bare = replace(account, email="")
        assert email_fragment(bare, redact=True) == ""
        assert email_fragment(bare, redact=False) == ""
