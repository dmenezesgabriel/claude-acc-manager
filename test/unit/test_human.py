"""Unit tests for cli.human.HumanOutput — the human-facing print sink.

The sink's contract: untrusted text (account names, emails, provider error
strings) is rendered literally — never parsed for [markup], never emoji-
substituted, never highlighted — and every line flushes so piped consumers
see a live stream.
"""

import itertools

import pytest
from rich.console import Console
from rich.text import Text
from support.recording_stream import RecordingStream

from claude_acc_manager.cli.human import HumanOutput


def _tty_out(stream: RecordingStream) -> HumanOutput:
    """A HumanOutput on a forced-color console writing to *stream*."""
    return HumanOutput(Console(file=stream, force_terminal=True, width=120))


class TestPrint:
    def test_print_writes_the_line_and_flushes(self):
        # arrange
        stream = RecordingStream()
        out = _tty_out(stream)

        # act
        out.print("hello")

        # assert
        assert stream.getvalue() == "hello\n"
        assert stream.events[-1] == "flush"

    def test_print_flushes_every_line(self):
        # arrange
        stream = RecordingStream()
        out = _tty_out(stream)

        # act
        out.print("one")
        out.print("two")
        out.print("three")

        # assert — every write is followed by a flush (the stream contract)
        groups = [list(g) for _, g in itertools.groupby(stream.events)]
        assert len(groups) % 2 == 0
        for writes, flush in zip(groups[::2], groups[1::2], strict=True):
            assert writes and set(writes) == {"write"}
            assert flush == ["flush"]

    def test_untrusted_brackets_are_not_markup_parsed(self):
        # arrange — an account name carrying markup-shaped text
        stream = RecordingStream()
        out = _tty_out(stream)

        # act
        out.print("added account '[bold]work[/]'")

        # assert — literal bytes, no ANSI style produced from the brackets
        text = stream.getvalue()
        assert "[bold]work[/]" in text
        assert "\x1b[" not in text

    def test_emoji_codes_are_not_substituted(self):
        # arrange
        stream = RecordingStream()
        out = _tty_out(stream)

        # act
        out.print("note :warning: literal")

        # assert
        assert ":warning:" in stream.getvalue()

    def test_a_text_renderable_keeps_its_own_style(self):
        # arrange — T5+ composes styled segments as Text; the sink must honor
        # spans carried in, only *parsing* is off
        stream = RecordingStream()
        out = _tty_out(stream)

        # act
        out.print(Text("switched", style="green"))

        # assert — ANSI is emitted when a Text asks for it
        assert "\x1b[32m" in stream.getvalue() or "\x1b[" in stream.getvalue()

    def test_a_text_renderable_is_not_folded_to_console_width(self):
        # arrange — narrower than the line; soft_wrap keeps it one row
        stream = RecordingStream()
        out = HumanOutput(Console(file=stream, width=10))

        # act
        out.print(Text("x" * 30))

        # assert — one long line, not three width-folded ones
        assert stream.getvalue() == "x" * 30 + "\n"

    def test_error_writes_to_the_err_console(self):
        # arrange
        out_stream = RecordingStream()
        err_stream = RecordingStream()
        out = HumanOutput(
            Console(file=out_stream, force_terminal=True),
            err_console=Console(file=err_stream, force_terminal=True),
        )

        # act
        out.error("error: nope")
        out.print("still fine")

        # assert — channels stay separate
        assert out_stream.getvalue() == "still fine\n"
        assert err_stream.getvalue() == "error: nope\n"
        assert err_stream.events[-1] == "flush"

    def test_default_construction_prints_to_real_stdout(self, capsys: pytest.CaptureFixture[str]):
        # act — no injection: the lazy console binds the real stream
        HumanOutput().print("plain")

        # assert — non-tty capture → zero ANSI
        assert capsys.readouterr().out == "plain\n"

    def test_default_error_goes_to_real_stderr(self, capsys: pytest.CaptureFixture[str]):
        # act
        HumanOutput().error("oops")

        # assert
        assert capsys.readouterr().err == "oops\n"


class TestStyled:
    """ANSI fragment for embedding inside a literal str row (list ``*``,
    flags, usage pcts) — the ``Text`` render path would expand ``\\t``, so
    styled fragments ride the verbatim ``str`` path instead.
    """

    def test_wraps_the_text_when_the_console_colors(self):
        # arrange
        stream = RecordingStream()
        out = _tty_out(stream)

        # act / assert — ANSI around the fragment, text inside untouched
        assert out.styled("hi", "bold") == "\x1b[1mhi\x1b[0m"

    def test_returns_plain_text_when_the_console_cannot_color(self):
        # arrange — no force_terminal: color_system is None
        stream = RecordingStream()
        out = HumanOutput(Console(file=stream))

        # act / assert — byte-identical passthrough
        assert out.styled("hi", "bold") == "hi"

    def test_stderr_fragments_follow_the_err_consoles_detection(self):
        # arrange — piped stdout, tty stderr: channels decide independently
        out = HumanOutput(
            Console(file=RecordingStream()),
            err_console=Console(file=RecordingStream(), force_terminal=True),
        )

        # act / assert
        assert out.styled("e", "red", stderr=True) == "\x1b[31me\x1b[0m"
        assert out.styled("e", "red") == "e"

    def test_honors_the_consoles_detected_color_system(self):
        # arrange — a 256-color console: "256" must reach Style.render,
        # not silently upgrade to the TRUECOLOR default
        out = HumanOutput(Console(file=RecordingStream(), color_system="256"))

        # act / assert — the hex downgrades to an eight-bit escape
        assert out.styled("x", "#d7a96c") == "\x1b[38;5;179mx\x1b[0m"

    def test_consoles_with_different_systems_do_not_share_codes(self):
        # arrange — stdout detects 256 colors, stderr truecolor: rich memoizes
        # ANSI codes on the shared parsed Style, so each console needs its own
        out = HumanOutput(
            Console(file=RecordingStream(), color_system="256"),
            err_console=Console(file=RecordingStream(), color_system="truecolor"),
        )

        # act — same style name on both channels
        stdout_frag = out.styled("x", "#d7a96c")
        stderr_frag = out.styled("x", "#d7a96c", stderr=True)

        # assert — each console's detected system, not the first render's
        assert stdout_frag == "\x1b[38;5;179mx\x1b[0m"
        assert stderr_frag == "\x1b[38;2;215;169;108mx\x1b[0m"


class TestSeverityStyle:
    """The CLI ramp — same WARN/CRIT edges as the TUI, named ANSI styles."""

    @pytest.mark.parametrize(
        ("pct", "expected"),
        [
            (0.0, "green"),
            (69.9, "green"),
            (70.0, "yellow"),
            (89.9, "yellow"),
            (90.0, "red"),
            (100.0, "red"),
        ],
    )
    def test_the_pct_ramp(self, pct: float, expected: str):
        # act / assert
        assert HumanOutput().severity_style(pct) == expected

    def test_unknown_usage_is_dim(self):
        # act / assert
        assert HumanOutput().severity_style(None) == "dim"


class TestEventStyle:
    @pytest.mark.parametrize(
        ("kind", "expected"),
        [
            ("switch", "green"),
            ("error", "red"),
            ("all-exhausted", "red"),
            ("account-quarantined", "yellow"),
            ("sleep", "dim"),
            ("no-switch", "dim"),
            ("poll", None),
            ("something-new", None),
        ],
    )
    def test_the_event_kind_map(self, kind: str, expected: str | None):
        # act / assert
        assert HumanOutput().event_style(kind) == expected
