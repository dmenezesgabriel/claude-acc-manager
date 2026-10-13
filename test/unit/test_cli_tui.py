"""TUI entry points — bare ``cam`` and the ``cam tui`` / ``cam watch`` commands.

Dispatch to the Textual app is patched via ``sys.modules`` with a named fake;
these tests pin *when* the dashboard launches and what exit code propagates.
"""

import sys
from pathlib import Path

import pytest
from support.cli_rigs import run_cli as _run
from support.fake_tui_module import FakeTuiModule
from support.use_cases import make_use_cases

from claude_acc_manager.cli import ProcessContext, UseCases, run

_use_cases = make_use_cases


class TestBareCamTui:
    """Bare ``cam`` opens the dashboard on an interactive terminal.

    ``interactive`` on the process context means both stdin and stdout are
    TTYs — without it (scripts, pipes, cron) bare ``cam`` keeps the usage
    fallback so shell tooling never launches a full-screen app.
    """

    def test_bare_cam_launches_the_dashboard_when_interactive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # arrange — the TUI module records rather than opening a terminal
        tui = FakeTuiModule()
        monkeypatch.setitem(sys.modules, "claude_acc_manager.tui", tui)

        # act
        code = run(
            [],
            _use_cases(tmp_path),
            process=ProcessContext(euid=1000, in_container=False, interactive=True),
        )

        # assert
        assert code == 0
        assert tui.starts == ["dashboard"]

    def test_bare_cam_with_no_argv_launches_the_dashboard(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # arrange — main() passes argv=None, deferring to sys.argv like
        # argparse; a bare sys.argv still triggers the swap
        tui = FakeTuiModule()
        monkeypatch.setitem(sys.modules, "claude_acc_manager.tui", tui)
        monkeypatch.setattr(sys, "argv", ["cam"])

        # act
        code = run(
            None,
            _use_cases(tmp_path),
            process=ProcessContext(euid=1000, in_container=False, interactive=True),
        )

        # assert
        assert code == 0
        assert tui.starts == ["dashboard"]

    def test_argv_none_defers_to_sys_argv_for_the_subcommand(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # arrange — regression: argv=None once meant *every* interactive
        # command opened the TUI instead of its own handler
        tui = FakeTuiModule()
        monkeypatch.setitem(sys.modules, "claude_acc_manager.tui", tui)
        monkeypatch.setattr(sys, "argv", ["cam", "list"])

        # act
        code = run(
            None,
            _use_cases(tmp_path),
            process=ProcessContext(euid=1000, in_container=False, interactive=True),
        )

        # assert — the list handler ran; the dashboard never started
        assert code == 0
        assert tui.starts == []

    def test_bare_cam_forwards_the_tui_exit_code(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # arrange
        tui = FakeTuiModule(exit_code=7)
        monkeypatch.setitem(sys.modules, "claude_acc_manager.tui", tui)

        # act
        code = run(
            [],
            _use_cases(tmp_path),
            process=ProcessContext(euid=1000, in_container=False, interactive=True),
        )

        # assert
        assert code == 7

    def test_bare_cam_prints_usage_without_an_interactive_terminal(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # arrange — the fake is armed but must never be reached
        tui = FakeTuiModule()
        monkeypatch.setitem(sys.modules, "claude_acc_manager.tui", tui)

        # act
        code = run(
            [],
            _use_cases(tmp_path),
            process=ProcessContext(euid=1000, in_container=False, interactive=False),
        )

        # assert
        assert code == 2
        assert "usage:" in capsys.readouterr().err
        assert tui.starts == []

    def test_bare_cam_interactive_still_obeys_the_root_guard(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # arrange — the TUI performs the same mutations as `cam switch`, so
        # the §8.6 refusal gates it like any dispatched command
        tui = FakeTuiModule()
        monkeypatch.setitem(sys.modules, "claude_acc_manager.tui", tui)

        # act
        code = run(
            [],
            _use_cases(tmp_path),
            process=ProcessContext(euid=0, in_container=False, interactive=True),
        )

        # assert
        assert code == 1
        assert "refusing to run as root" in capsys.readouterr().err
        assert tui.starts == []

    def test_a_subcommand_still_dispatches_when_interactive(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # arrange — interactive swaps only the *bare* invocation, not any argv
        tui = FakeTuiModule()
        monkeypatch.setitem(sys.modules, "claude_acc_manager.tui", tui)

        # act
        code = run(
            ["list"],
            _use_cases(tmp_path),
            process=ProcessContext(euid=1000, in_container=False, interactive=True),
        )

        # assert
        assert code == 0
        assert capsys.readouterr().out == "no accounts registered\n"
        assert tui.starts == []


class TestTuiEntryPoints:
    """`cam tui` / `cam watch` hand off to the TUI runner with a start screen."""

    @staticmethod
    def _capture_run(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
        """Swap the TUI runner for a recorder — the real one owns the terminal."""
        captured: dict[str, object] = {}

        def fake_run(use_cases: UseCases, *, start: str) -> int:
            captured["start"] = start
            captured["use_cases"] = use_cases
            return 0

        import claude_acc_manager.tui

        monkeypatch.setattr(claude_acc_manager.tui, "run", fake_run)
        return captured

    def test_tui_opens_the_dashboard(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        captured = self._capture_run(monkeypatch)
        use_cases = _use_cases(tmp_path)

        code = _run(["tui"], use_cases)

        assert code == 0
        assert captured["start"] == "dashboard"
        assert captured["use_cases"] is use_cases

    def test_watch_opens_the_watch_screen(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        captured = self._capture_run(monkeypatch)
        use_cases = _use_cases(tmp_path)

        code = _run(["watch"], use_cases)

        assert code == 0
        assert captured["start"] == "watch"
        assert captured["use_cases"] is use_cases
