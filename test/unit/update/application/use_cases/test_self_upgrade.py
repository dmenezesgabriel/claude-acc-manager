"""Unit tests for update.application.use_cases.self_upgrade.

cam upgrade delegates to whoever installed it: the use case turns the
detected InstallMethod into the manager's argv and passes the child's exit
code through verbatim. Installs it cannot reason about — VCS/UNKNOWN, or a
pipx pin — refuse with ManualUpgradeError so the transport can print the
manual path; a blind upgrade is worse than none (claude-swap's rule).
"""

import pytest
from support.fake_upgrade_runner import FakeUpgradeRunner

from claude_acc_manager.update.application.ports import UpgradeToolMissingError
from claude_acc_manager.update.application.use_cases.self_upgrade import (
    ManualUpgradeError,
    SelfUpgrade,
)
from claude_acc_manager.update.domain.services.install_method import InstallMethod


def make_upgrade(
    runner: FakeUpgradeRunner | None = None, *, method: InstallMethod = InstallMethod.UV
) -> tuple[SelfUpgrade, FakeUpgradeRunner]:
    """A SelfUpgrade over a recording runner (a uv install by default)."""
    runner = runner if runner is not None else FakeUpgradeRunner()
    return SelfUpgrade(runner, method=method), runner


class TestDelegation:
    @pytest.mark.parametrize(
        ("method", "argv"),
        [
            (InstallMethod.UV, ["uv", "tool", "upgrade", "claude-acc-manager"]),
            (InstallMethod.PIPX, ["pipx", "upgrade", "claude-acc-manager"]),
        ],
    )
    def test_runs_the_managers_argv_and_returns_its_code(
        self, method: InstallMethod, argv: list[str]
    ) -> None:
        # Arrange
        upgrade, runner = make_upgrade(method=method)

        # Act
        rc = upgrade.execute()

        # Assert — argv verbatim, rc verbatim: the manager owns both
        assert runner.calls == [argv]
        assert rc == 0

    def test_a_uv_install_honors_the_target_pin(self) -> None:
        # Arrange
        upgrade, runner = make_upgrade()

        # Act
        upgrade.execute("1.2.0")

        # Assert — uv's name==version specifier carries the pin
        assert runner.calls == [["uv", "tool", "upgrade", "claude-acc-manager==1.2.0"]]

    def test_a_nonzero_manager_exit_passes_through(self) -> None:
        # the child's own stderr said why; cam only forwards the code
        upgrade, _ = make_upgrade(runner=FakeUpgradeRunner(returncode=3))

        # Act / Assert
        assert upgrade.execute() == 3


class TestManualRefusals:
    @pytest.mark.parametrize("method", [InstallMethod.VCS, InstallMethod.UNKNOWN])
    @pytest.mark.parametrize("target", [None, "1.2.0"])
    def test_an_undelegable_install_raises_manual_upgrade_required(
        self, method: InstallMethod, target: str | None
    ) -> None:
        # Arrange
        upgrade, runner = make_upgrade(method=method)

        # Act
        with pytest.raises(ManualUpgradeError) as raised:
            upgrade.execute(target)

        # Assert — the refusal carries what the transport renders; nothing ran
        assert raised.value.method is method
        assert raised.value.target == target
        assert runner.calls == []

    def test_a_pipx_install_cannot_pin(self) -> None:
        # `pipx upgrade` takes no version specifier — pinning is manual there
        upgrade, runner = make_upgrade(method=InstallMethod.PIPX)

        # Act
        with pytest.raises(ManualUpgradeError) as raised:
            upgrade.execute("1.2.0")

        # Assert
        assert raised.value.method is InstallMethod.PIPX
        assert raised.value.target == "1.2.0"
        assert runner.calls == []

    @pytest.mark.parametrize(
        ("method", "target", "expected"),
        [
            (InstallMethod.VCS, None, "cannot self-upgrade a 'vcs' install"),
            (InstallMethod.UNKNOWN, "1.2.0", "cannot self-upgrade a 'unknown' install to '1.2.0'"),
        ],
    )
    def test_the_refusal_carries_a_fallback_message(
        self, method: InstallMethod, target: str | None, expected: str
    ) -> None:
        # str() is the wording a transport falls back to if it shows the raw error
        assert str(ManualUpgradeError(method, target)) == expected


class TestToolMissing:
    def test_a_missing_manager_propagates_the_named_error(self) -> None:
        # UpgradeToolMissingError is the port's named FileNotFoundError — the
        # transport prints it, so the use case must not swallow it
        runner = FakeUpgradeRunner(
            error=UpgradeToolMissingError("upgrade tool 'uv' is not on PATH")
        )
        upgrade, _ = make_upgrade(runner=runner)

        # Act / Assert
        with pytest.raises(UpgradeToolMissingError):
            upgrade.execute()
