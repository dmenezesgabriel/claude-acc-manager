"""``cam upgrade`` — delegation to the detected install manager.

The upgrade runner and install-method probe are fakes; the tests pin which
command line each install method produces and how failures render.
"""

import sys
from pathlib import Path

import pytest
from rich.console import Console
from support.cli_rigs import run_cli as _run
from support.cli_rigs import upgrade_rig as _upgrade
from support.fake_upgrade_runner import FakeUpgradeRunner
from support.recording_stream import RecordingStream

from claude_acc_manager.cli import ProcessContext, run
from claude_acc_manager.update.application.ports import UpgradeToolMissingError
from claude_acc_manager.update.domain.services.install_method import InstallMethod


class TestUpgradeCommand:
    """`cam upgrade [target]` — delegate to the installer, or print the manual path."""

    def test_a_uv_install_delegates_and_exits_with_the_managers_code(self, tmp_path: Path):
        # arrange
        use_cases, runner = _upgrade(tmp_path, InstallMethod.UV)

        # act
        code = _run(["upgrade"], use_cases)

        # assert — argv verbatim, rc 0 verbatim; the child's own output spoke
        assert code == 0
        assert runner.calls == [["uv", "tool", "upgrade", "claude-acc-manager"]]

    def test_a_pipx_install_delegates_through_pipx_upgrade(self, tmp_path: Path):
        # arrange
        use_cases, runner = _upgrade(tmp_path, InstallMethod.PIPX)

        # act
        code = _run(["upgrade"], use_cases)

        # assert
        assert code == 0
        assert runner.calls == [["pipx", "upgrade", "claude-acc-manager"]]

    def test_a_target_pins_the_uv_upgrade(self, tmp_path: Path):
        # arrange — `uv tool upgrade` accepts a name==version specifier
        use_cases, runner = _upgrade(tmp_path, InstallMethod.UV)

        # act
        code = _run(["upgrade", "1.2.0"], use_cases)

        # assert
        assert code == 0
        assert runner.calls == [["uv", "tool", "upgrade", "claude-acc-manager==1.2.0"]]

    def test_the_managers_nonzero_code_is_the_commands(self, tmp_path: Path):
        # a failed upgrade keeps its rc — the child's stderr already said why
        use_cases, _ = _upgrade(tmp_path, InstallMethod.UV, FakeUpgradeRunner(returncode=2))

        # act / assert
        assert _run(["upgrade"], use_cases) == 2

    def test_an_unknown_install_prints_the_manual_list_and_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        use_cases, runner = _upgrade(tmp_path, InstallMethod.UNKNOWN)

        # act
        code = _run(["upgrade"], use_cases)

        # assert — nothing ran; the manual paths are claude-swap's list
        captured = capsys.readouterr()
        assert code == 1
        assert runner.calls == []
        assert captured.out == ""
        assert captured.err == (
            "error: could not detect how cam was installed "
            "(looked for a uv tool or pipx venv)\n"
            f"  sys.prefix:     {sys.prefix}\n"
            f"  sys.executable: {sys.executable}\n"
            "to upgrade manually, run one of:\n"
            "  uv tool upgrade claude-acc-manager\n"
            "  pipx upgrade claude-acc-manager\n"
            f"  {sys.executable} -m pip install --upgrade claude-acc-manager\n"
            "if cam came from a git checkout, `git pull` upgrades it instead\n"
        )

    def test_a_vcs_install_points_back_at_its_source(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — a git/path receipt: `uv tool upgrade` would re-resolve the
        # ref, not the release, so delegation is refused outright
        use_cases, _ = _upgrade(tmp_path, InstallMethod.VCS)

        # act
        code = _run(["upgrade"], use_cases)

        # assert
        captured = capsys.readouterr()
        assert code == 1
        assert captured.out == ""
        assert captured.err == (
            "error: cam was installed from a source checkout, not a package index\n"
            "  upgrade by re-installing from that source "
            "(e.g. `git pull` in the checkout)\n"
        )

    def test_a_pipx_install_cannot_pin_a_target(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — `pipx upgrade` takes no version specifier
        use_cases, runner = _upgrade(tmp_path, InstallMethod.PIPX)

        # act
        code = _run(["upgrade", "1.2.0"], use_cases)

        # assert — the refusal names the pipx pin path verbatim
        captured = capsys.readouterr()
        assert code == 1
        assert runner.calls == []
        assert captured.out == ""
        assert captured.err == (
            "error: `pipx upgrade` cannot pin a version\n"
            "  run `pipx install --force claude-acc-manager==1.2.0` for that release,\n"
            "  or a bare `cam upgrade` for the latest\n"
        )

    def test_a_missing_manager_names_it_on_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — UpgradeToolMissingError is the port's named FileNotFoundError
        runner = FakeUpgradeRunner(
            error=UpgradeToolMissingError("upgrade tool 'uv' is not on PATH")
        )
        use_cases, _ = _upgrade(tmp_path, InstallMethod.UV, runner)

        # act
        code = _run(["upgrade"], use_cases)

        # assert
        captured = capsys.readouterr()
        assert code == 1
        assert captured.out == ""
        assert captured.err == "error: upgrade tool 'uv' is not on PATH\n"

    def test_the_error_prefix_stays_red_with_a_piped_stdout(self, tmp_path: Path):
        # arrange — stdout piped (no color), stderr a tty (color): the
        # fragment must follow the *err* console's detection
        err_stream = RecordingStream()
        runner = FakeUpgradeRunner(
            error=UpgradeToolMissingError("upgrade tool 'uv' is not on PATH")
        )
        use_cases, _ = _upgrade(tmp_path, InstallMethod.UV, runner)

        # act
        code = run(
            ["upgrade"],
            use_cases,
            process=ProcessContext(euid=1000, in_container=False),
            console=Console(file=RecordingStream()),
            err_console=Console(file=err_stream, force_terminal=True),
        )

        # assert — red survives stdout losing its color
        assert code == 1
        assert err_stream.getvalue() == "\x1b[31merror:\x1b[0m upgrade tool 'uv' is not on PATH\n"

    def test_the_manual_path_error_stays_red_with_a_piped_stdout(self, tmp_path: Path):
        # arrange — same asymmetric rig on the _print_manual_upgrade site
        err_stream = RecordingStream()
        use_cases, _ = _upgrade(tmp_path, InstallMethod.UNKNOWN)

        # act
        code = run(
            ["upgrade"],
            use_cases,
            process=ProcessContext(euid=1000, in_container=False),
            console=Console(file=RecordingStream()),
            err_console=Console(file=err_stream, force_terminal=True),
        )

        # assert
        assert code == 1
        assert err_stream.getvalue().startswith("\x1b[31merror:\x1b[0m ")
