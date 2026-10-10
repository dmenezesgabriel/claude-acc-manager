"""Unit tests for update.infrastructure.subprocess_upgrade_runner and the
UpgradeRunnerPort it implements."""

import subprocess

import pytest

import claude_acc_manager.update.infrastructure.subprocess_upgrade_runner as runner_module
from claude_acc_manager.update.application.ports import (
    UpgradeRunnerPort,
    UpgradeToolMissingError,
)
from claude_acc_manager.update.infrastructure.subprocess_upgrade_runner import (
    SubprocessUpgradeRunner,
)


class FakeSubprocessRun:
    """Named fake for subprocess.run — records argv+kwargs, honors ``check``."""

    def __init__(self, returncode: int = 0) -> None:
        self._returncode = returncode
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def __call__(self, args: list[str], **kwargs: object) -> "subprocess.CompletedProcess[str]":
        self.calls.append((args, dict(kwargs)))
        if kwargs.get("check") and self._returncode:
            raise subprocess.CalledProcessError(self._returncode, args)
        return subprocess.CompletedProcess(args, self._returncode, "", "")


def fake_run_raising(monkeypatch: pytest.MonkeyPatch, error: OSError) -> None:
    def _run(args: list[str], **kwargs: object) -> "subprocess.CompletedProcess[str]":
        raise error

    monkeypatch.setattr(runner_module.subprocess, "run", _run)


class TestSubprocessUpgradeRunnerAdaptsThePort:
    def test_is_an_upgrade_runner_port(self):
        assert isinstance(SubprocessUpgradeRunner(), UpgradeRunnerPort)


class TestRun:
    def test_passes_the_argv_through_and_returns_the_exit_code(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        # arrange
        fake = FakeSubprocessRun(returncode=7)
        monkeypatch.setattr(runner_module.subprocess, "run", fake)
        argv = ["uv", "tool", "upgrade", "claude-acc-manager"]

        # act
        rc = SubprocessUpgradeRunner().run(argv)

        # assert
        assert rc == 7
        [(args, kwargs)] = fake.calls
        assert args == argv
        # check=False keeps a non-zero upgrade exit as an rc the caller can
        # report; no capture_output/timeout — the manager's progress and
        # prompts reach the terminal, and upgrades legitimately take minutes
        assert kwargs == {"check": False}

    def test_a_missing_executable_raises_the_named_error(self, monkeypatch: pytest.MonkeyPatch):
        # arrange
        argv = ["uv", "tool", "upgrade", "claude-acc-manager"]
        fake_run_raising(monkeypatch, FileNotFoundError(2, "No such file or directory"))

        # act
        with pytest.raises(UpgradeToolMissingError) as raised:
            SubprocessUpgradeRunner().run(argv)

        # assert
        assert str(raised.value) == (f"upgrade tool 'uv' from argv {argv!r} is not on PATH")
