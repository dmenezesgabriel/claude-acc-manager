"""``cam auto`` loop mode — signal wiring, the banner, and emit flushing.

The loop owns its SIGTERM handler and prints a banner unless ``--json``;
``test_emit_flushes_every_printed_line`` pins the streaming contract for both
channels (docs/architecture.md §10).
"""

import signal
import threading
import time
from pathlib import Path

import pytest
from rich.console import Console
from support.cli_rigs import STAMP as _STAMP
from support.cli_rigs import auto_credentials as _auto_credentials
from support.cli_rigs import auto_rig as _auto_rig
from support.cli_rigs import run_cli as _run
from support.cli_rigs import snap_used as _snap_used
from support.cli_rigs import until as _until
from support.recording_stream import RecordingStream

from claude_acc_manager.cli import ProcessContext, run


class TestAutoLoop:
    """``cam auto`` without ``--once`` — loop lifecycle and output channels."""

    def test_loop_sigterm_stops_the_loop_cleanly(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ):
        # arrange — capture the handler cmd_auto installs instead of signaling;
        # the exhausted scenario lands the loop in its long-sleep branch
        installed: dict[int, object] = {}
        monkeypatch.setattr(
            signal, "signal", lambda sig, handler: installed.setdefault(sig, handler)
        )
        reset = 1_000_270.66  # sleep 330.66s: disambiguates /60 (5.5→"6m")
        use_cases = _auto_rig(
            tmp_path,
            snaps={
                "at-x": _snap_used(100.0, reset_s=reset),
                "at-y": _snap_used(100.0, reset_s=reset),
            },
            credentials=_auto_credentials("x", "y"),
        )
        box: dict[str, int] = {}
        thread = threading.Thread(
            target=lambda: box.setdefault("code", _run(["auto"], use_cases)),
            daemon=True,
        )

        # act — let the first tick land, then deliver the signal
        thread.start()
        assert _until(lambda: installed)
        time.sleep(0.3)
        installed[signal.SIGTERM](signal.SIGTERM, None)
        thread.join(timeout=5.0)

        # assert — a tick ran, the MAX_SLEEP-capped sleep was interrupted
        assert not thread.is_alive()
        assert box["code"] == 0
        out = capsys.readouterr().out
        assert out.startswith("auto-switch running: threshold 90%, every 60s — Ctrl-C to stop\n")
        assert f"{_STAMP}  sleeping 6m (until 1970-01-12T13:52:10Z)\n" in out

    def test_once_best_strategy_prefers_the_roomiest_candidate(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — z holds more headroom than y; only "best" reaches it
        use_cases = _auto_rig(
            tmp_path,
            snaps={
                "at-x": _snap_used(95.0),
                "at-y": _snap_used(50.0),
                "at-z": _snap_used(20.0),
            },
            credentials=_auto_credentials("x", "y", "z"),
            parked=("y", "z"),
        )

        # act
        code = _run(["auto", "--once", "--strategy", "best"], use_cases)

        # assert
        assert code == 0
        assert f"{_STAMP}  Switched x -> z (proactive)\n" in capsys.readouterr().out

    def test_once_next_available_takes_the_first_eligible(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — same rig as "best"; the flag changes the pick to y
        use_cases = _auto_rig(
            tmp_path,
            snaps={
                "at-x": _snap_used(95.0),
                "at-y": _snap_used(50.0),
                "at-z": _snap_used(20.0),
            },
            credentials=_auto_credentials("x", "y", "z"),
            parked=("y", "z"),
        )

        # act
        code = _run(["auto", "--once", "--strategy", "next-available"], use_cases)

        # assert
        assert code == 0
        assert f"{_STAMP}  Switched x -> y (proactive)\n" in capsys.readouterr().out

    def test_loop_banner_echoes_interval_and_dry_run(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ):
        # arrange
        installed: dict[int, object] = {}
        monkeypatch.setattr(
            signal, "signal", lambda sig, handler: installed.setdefault(sig, handler)
        )
        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(50.0)},
            credentials=_auto_credentials("x"),
        )
        thread = threading.Thread(
            target=lambda: _run(["auto", "--interval", "15", "--dry-run"], use_cases),
            daemon=True,
        )

        # act
        thread.start()
        assert _until(lambda: installed)
        time.sleep(0.3)
        installed[signal.SIGTERM](signal.SIGTERM, None)
        thread.join(timeout=5.0)

        # assert — the flag values reach the banner verbatim
        assert not thread.is_alive()
        out = capsys.readouterr().out
        assert out.startswith(
            "auto-switch running: threshold 90%, every 15s (dry-run) — Ctrl-C to stop\n"
        )

    def test_emit_flushes_every_printed_line(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — JSONL is a stream contract: every line must reach the
        # consumer unbuffered. Human lines go through the console (flushes
        # per print); JSONL stays on builtins.print(flush=True).
        stream = RecordingStream()
        kwargs_log: list[dict[str, object]] = []
        real_print = print
        monkeypatch.setattr(
            "builtins.print",
            lambda *a, **kw: (kwargs_log.append(dict(kw)), real_print(*a, **kw)),
        )
        rig = lambda: _auto_rig(  # noqa: E731 — test-local scenario factory
            tmp_path,
            snaps={"at-x": _snap_used(50.0)},
            credentials=_auto_credentials("x"),
        )

        # act — one human run, one JSONL run (fresh rigs)
        assert (
            run(
                ["auto", "--once"],
                rig(),
                process=ProcessContext(euid=1000, in_container=False),
                console=Console(file=stream, width=120),
            )
            == 2
        )
        assert _run(["auto", "--once", "--json"], rig()) == 2

        # assert — human lines: a flush after every write batch; jsonl: flush kwarg
        assert stream.events
        assert stream.events.count("flush") >= len(stream.getvalue().splitlines())
        assert kwargs_log
        assert all(kw.get("flush") is True for kw in kwargs_log)
