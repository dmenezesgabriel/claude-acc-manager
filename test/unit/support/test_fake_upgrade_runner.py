"""Contract tests for the shared FakeUpgradeRunner fake."""

import pytest
from support.fake_upgrade_runner import FakeUpgradeRunner

from claude_acc_manager.update.application.ports import UpgradeRunnerPort


class TestFakeUpgradeRunnerAdaptsThePort:
    def test_is_an_upgrade_runner_port(self):
        assert isinstance(FakeUpgradeRunner(), UpgradeRunnerPort)


class TestRun:
    def test_returns_the_pinned_exit_code(self):
        # arrange / act / assert
        assert FakeUpgradeRunner(returncode=3).run(["uv"]) == 3

    def test_records_each_argv_in_order(self):
        # arrange
        runner = FakeUpgradeRunner()

        # act
        runner.run(["uv", "tool", "upgrade", "cam"])
        runner.run(["pipx", "upgrade", "cam"])

        # assert
        assert runner.calls == [
            ["uv", "tool", "upgrade", "cam"],
            ["pipx", "upgrade", "cam"],
        ]

    def test_raises_the_pinned_error(self):
        # arrange / act / assert
        with pytest.raises(FileNotFoundError):
            FakeUpgradeRunner(error=FileNotFoundError()).run(["uv"])
