"""``cam auto --json`` — the JSONL envelope is the machine contract.

Each event is one line; dead lineages and logged-out state report through the
same schema as live switches (docs/architecture.md §10).
"""

import json
import signal
import threading
import time
from pathlib import Path

import pytest
from support.cli_rigs import auto_credentials as _auto_credentials
from support.cli_rigs import auto_rig as _auto_rig
from support.cli_rigs import dead_lineage_rig as _dead_lineage_rig
from support.cli_rigs import run_cli as _run
from support.cli_rigs import snap_used as _snap_used
from support.cli_rigs import until as _until
from support.in_memory_auto_state import InMemoryAutoState
from support.use_cases import make_use_cases

from claude_acc_manager.auto.domain.auto_state import AutoState

_use_cases = make_use_cases


class TestAutoJson:
    """``cam auto --json`` — one event object per line, on ``--once`` and ``--loop``."""

    def test_once_json_emits_one_event_object_per_line(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(100.0), "at-y": _snap_used(100.0)},
            credentials=_auto_credentials("x", "y"),
        )

        # act
        code = _run(["auto", "--once", "--json"], use_cases)

        # assert — JSONL: every line is its own object; the exit still codes
        assert code == 3
        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert [line["event"] for line in lines] == ["poll", "all-exhausted"]
        assert all(line["schemaVersion"] == 1 and line["ts"] for line in lines)
        assert lines[0]["active"] == "x"
        assert lines[0]["headroomPct"] == {"x": 0.0, "y": 0.0}
        assert lines[0]["threshold"] == 90
        assert lines[0]["windowsPct"] == {"x": {"5h": 100.0}, "y": {"5h": 100.0}}
        assert lines[1]["earliestResetAt"] is None

    def test_once_json_reports_the_earliest_reset(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — every account maxed; x's window resets first
        use_cases = _auto_rig(
            tmp_path,
            snaps={
                "at-x": _snap_used(100.0, 1_003_600.0),
                "at-y": _snap_used(100.0, 1_007_200.0),
            },
            credentials=_auto_credentials("x", "y"),
        )

        # act
        code = _run(["auto", "--once", "--json"], use_cases)

        # assert — the earliest reset rides the all-exhausted payload
        assert code == 3
        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert lines[1]["event"] == "all-exhausted"
        assert lines[1]["earliestResetAt"] == "1970-01-12T14:46:40Z"

    def test_loop_json_suppresses_the_banner(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ):
        # arrange — the exhausted scenario also lands the sleep event in JSONL;
        # the fractional clock makes `seconds` non-integral, so `round()`
        # mutants (None/0/2 digits) can't smuggle the same value through
        installed: dict[int, object] = {}
        monkeypatch.setattr(
            signal, "signal", lambda sig, handler: installed.setdefault(sig, handler)
        )
        reset = 1_000_270.0
        use_cases = _auto_rig(
            tmp_path,
            snaps={
                "at-x": _snap_used(100.0, reset_s=reset),
                "at-y": _snap_used(100.0, reset_s=reset),
            },
            credentials=_auto_credentials("x", "y"),
            clock_s=1_000_000.54,
        )
        thread = threading.Thread(target=lambda: _run(["auto", "--json"], use_cases), daemon=True)

        # act
        thread.start()
        assert _until(lambda: installed)
        time.sleep(0.3)
        installed[signal.SIGTERM](signal.SIGTERM, None)
        thread.join(timeout=5.0)

        # assert — JSONL purity: no banner, every line is its own event object
        assert not thread.is_alive()
        out = capsys.readouterr().out
        assert "auto-switch running" not in out
        lines = [json.loads(line) for line in out.splitlines()]
        assert [line["event"] for line in lines] == ["poll", "all-exhausted", "sleep"]
        assert '"seconds": 329.5' in out
        assert lines[2]["until"] == "1970-01-12T13:52:10Z"

    def test_once_json_marks_a_dead_lineage(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — a second rig: quarantine persists and would skew a rerun
        use_cases = _dead_lineage_rig(tmp_path)

        # act
        code = _run(["auto", "--once", "--json"], use_cases)

        # assert
        assert code == 3
        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert [line["event"] for line in lines] == [
            "poll",
            "account-quarantined",
            "no-switch",
        ]
        assert lines[1]["name"] == "y"
        assert lines[1]["reason"] == "invalid_grant"
        assert lines[2]["reason"] == "no-viable-target"

    def test_once_json_renders_a_switch(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange
        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(95.0), "at-y": _snap_used(20.0)},
            credentials=_auto_credentials("x", "y"),
        )

        # act
        code = _run(["auto", "--once", "--json"], use_cases)

        # assert
        assert code == 0
        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert lines[1]["event"] == "switch"
        assert lines[1]["trigger"] == "proactive"
        assert lines[1]["from"] == "x" and lines[1]["to"] == "y"
        assert lines[1]["dryRun"] is False

    def test_once_json_renders_an_error(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange — the state port dies inside the tick's never-raises net
        class _RaisingAutoState(InMemoryAutoState):
            def load(self) -> AutoState:
                raise RuntimeError("boom")

        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(50.0)},
            credentials=_auto_credentials("x"),
            auto_state=_RaisingAutoState(),
        )

        # act
        code = _run(["auto", "--once", "--json"], use_cases)

        # assert
        assert code == 1
        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert lines[-1]["event"] == "error"
        assert lines[-1]["message"] == "RuntimeError: boom"
        assert lines[-1]["transient"] is True

    def test_once_json_logged_out_reports_null_active(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = _run(["auto", "--once", "--json"], _use_cases(tmp_path))

        # assert
        assert code == 2
        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert [line["event"] for line in lines] == ["poll", "no-switch"]
        assert lines[0]["active"] is None
        assert lines[1]["reason"] == "no-active-account"
        assert lines[1]["detail"] == "log in and run 'cam add' first"
