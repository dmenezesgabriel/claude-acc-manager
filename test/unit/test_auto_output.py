"""Unit tests for cli.auto_output — severity-colored auto event lines.

The human transport's contract: each event kind carries a whole-line
severity style, while ``poll`` stays plain except its used-pct segment,
which rides the shared WARN/CRIT ramp. Line wording itself is pinned in
``test_cli.py``; these tests pin the styling only.
"""

import pytest
from rich.console import Console
from rich.text import Text
from support.controllable_clock import ControllableClock
from support.recording_stream import RecordingStream
from support.rich_asserts import text_style_at

from claude_acc_manager.auto.domain.auto_event import (
    AllExhaustedEvent,
    AutoEvent,
    ErrorEvent,
    NoSwitchEvent,
    PollEvent,
    QuarantinedEvent,
    SleepEvent,
    SwitchEvent,
)
from claude_acc_manager.cli.auto_output import auto_emit, banner_text, render_event
from claude_acc_manager.cli.human import HumanOutput
from claude_acc_manager.settings.domain.settings_spec import AutoSettings

_CLOCK = ControllableClock(now_epoch_s=1_000_000.0)
_STAMP = "13:46:40"


class TestRenderEvent:
    @pytest.mark.parametrize(
        ("event", "style"),
        [
            (SwitchEvent(trigger="proactive", from_name="x", to_name="y"), "green"),
            (ErrorEvent(message="boom"), "red"),
            (AllExhaustedEvent(earliest_reset_at_s=None), "red"),
            (QuarantinedEvent(name="x", reason="401"), "yellow"),
            (SleepEvent(seconds=300.0, until="03:51:40"), "dim"),
            (NoSwitchEvent(reason="below-threshold", detail="50% < 90%"), "dim"),
        ],
    )
    def test_the_event_kind_carries_a_whole_line_style(self, event: AutoEvent, style: str):
        # act
        rendered = render_event(_CLOCK, event, HumanOutput())

        # assert — the kind's style is the Text's base style, stamp to end
        assert isinstance(rendered, Text)
        assert rendered.plain.startswith(f"{_STAMP}  ")
        assert str(rendered.style) == style

    def test_an_unmapped_event_kind_stays_plain(self):
        # arrange — a future kind the style map has never heard of
        class OddEvent(AutoEvent):
            kind = "odd"

        # act
        rendered = render_event(_CLOCK, OddEvent(), HumanOutput())

        # assert — plain str, no style lookup crash
        assert rendered == f"{_STAMP}  odd"

    def test_a_poll_line_colors_the_used_pct_by_severity(self):
        # arrange — 95% used sits over the CRIT edge
        event = PollEvent(
            active="x",
            headroom={"x": 5.0},
            threshold=90.0,
            fetch_errors={},
            windows={"x": {"5h": 95.0}},
        )

        # act
        rendered = render_event(_CLOCK, event, HumanOutput())

        # assert — only the pct segment is styled; the rest stays plain
        assert isinstance(rendered, Text)
        assert rendered.plain == f"{_STAMP}  x: 95% used (switch at 90%)"
        pct_offset = rendered.plain.index("95% used")
        assert text_style_at(rendered, pct_offset) == "red"
        assert text_style_at(rendered, 0) == ""

    @pytest.mark.parametrize(
        ("used_pct", "style"),
        [(50.0, "green"), (80.0, "yellow"), (95.0, "red")],
    )
    def test_the_poll_pct_rides_the_ramp(self, used_pct: float, style: str):
        # arrange
        event = PollEvent(
            active="x",
            headroom={"x": 100.0 - used_pct},
            threshold=90.0,
            fetch_errors={},
            windows={},
        )

        # act
        rendered = render_event(_CLOCK, event, HumanOutput())

        # assert
        assert isinstance(rendered, Text)
        pct_offset = rendered.plain.index(f"{used_pct:.0f}% used")
        assert text_style_at(rendered, pct_offset) == style

    def test_a_poll_with_unknown_usage_reads_dim(self):
        # arrange — no headroom and no cause: genuinely unknown
        event = PollEvent(
            active="x",
            headroom={},
            threshold=90.0,
            fetch_errors={},
            windows={},
        )

        # act
        rendered = render_event(_CLOCK, event, HumanOutput())

        # assert — dim, not alarming
        assert isinstance(rendered, Text)
        assert rendered.plain == f"{_STAMP}  x: usage unknown (switch at 90%)"
        assert text_style_at(rendered, rendered.plain.index("usage unknown")) == "dim"


class TestBannerText:
    def test_the_banner_is_bold(self):
        # arrange
        settings = AutoSettings(threshold=90.0, interval_seconds=60.0)

        # act
        banner = banner_text(settings, dry_run=False)

        # assert
        assert banner.plain == "auto-switch running: threshold 90%, every 60s — Ctrl-C to stop"
        assert str(banner.style) == "bold"

    def test_the_banner_marks_dry_run(self):
        # arrange
        settings = AutoSettings(threshold=90.0, interval_seconds=60.0)

        # act / assert
        assert " (dry-run)" in banner_text(settings, dry_run=True).plain


class TestAutoEmit:
    def test_the_human_sink_writes_the_styled_line(self):
        # arrange — a forced-color console so ANSI is observable
        stream = RecordingStream()
        out = HumanOutput(Console(file=stream, force_terminal=True, width=120))
        emit = auto_emit(False, _CLOCK, out)

        # act
        emit(SwitchEvent(trigger="proactive", from_name="x", to_name="y"))

        # assert — green ANSI, same visible wording, flushed
        text = stream.getvalue()
        assert "\x1b[32m" in text
        assert "Switched x -> y (proactive)" in text
        assert stream.events[-1] == "flush"
