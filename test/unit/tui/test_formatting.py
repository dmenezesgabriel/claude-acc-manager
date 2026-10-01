"""Compact human durations for the TUI status line."""

import pytest

from claude_acc_manager.tui.formatting import format_duration


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
