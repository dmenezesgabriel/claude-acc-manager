"""SelfUpgrade use case — `cam upgrade` delegates to whoever installed cam.

cam never edits its own install: the detected :class:`InstallMethod` picks
the manager argv (``uv tool upgrade`` / ``pipx upgrade``) and the child
inherits the terminal, so progress and any prompts reach the user and the
child's exit code is the result — a failed upgrade keeps its rc because the
manager's own stderr already said why.

Installs that cannot be delegated — a VCS/source checkout (``uv tool
upgrade`` would re-resolve the ref, not the release), an undetectable
method, or a version pin under pipx (``pipx upgrade`` takes no specifier) —
raise :class:`ManualUpgradeError`; the transport renders the manual path
and exits 1. A manager binary absent from PATH surfaces as the port's named
:class:`UpgradeToolMissingError`, which propagates untouched.

Example:
    rc = SelfUpgrade(SubprocessUpgradeRunner(), method=InstallMethod.UV).execute()
"""

from claude_acc_manager.update.application.ports import UpgradeRunnerPort
from claude_acc_manager.update.domain.services.install_method import (
    InstallMethod,
    upgrade_argv,
)

__all__ = ["ManualUpgradeError", "SelfUpgrade"]


class ManualUpgradeError(Exception):
    """The install cannot be delegated to a package manager.

    Carries the ``method`` and ``target`` the transport needs to render the
    manual path (a source checkout, an unknown installer, a pipx pin); the
    message is only a fallback for a transport that shows it raw.
    """

    def __init__(self, method: InstallMethod, target: str | None = None) -> None:
        """Record the refusal's method and target for the transport's render."""
        self.method = method
        self.target = target
        suffix = f" to {target!r}" if target is not None else ""
        super().__init__(f"cannot self-upgrade a {method.value!r} install{suffix}")


class SelfUpgrade:
    """Run the detected package manager's upgrade of cam.

    Example:
        ``SelfUpgrade(runner, method=InstallMethod.PIPX).execute() == 0``
    """

    def __init__(self, runner: UpgradeRunnerPort, *, method: InstallMethod) -> None:
        """Store the injected runner and the already-detected install method.

        *method* arrives resolved at the composition root (the ``mode=``
        injection precedent from ``CheckUpdate``) — the use case stays free
        of prefix/receipt I/O.
        """
        self._runner = runner
        self._method = method

    def execute(self, target: str | None = None) -> int:
        """Run the manager's upgrade argv and return its exit code.

        *target* pins the release (``claude-acc-manager==<target>``) where
        the manager accepts a specifier — uv only.

        Raises:
            ManualUpgradeError: The install cannot be delegated (VCS,
                UNKNOWN, or a pipx pin) — print the manual path instead.
            UpgradeToolMissingError: The manager is not on PATH.
        """
        argv = upgrade_argv(self._method, target)
        if argv is None:
            raise ManualUpgradeError(self._method, target)
        return self._runner.run(argv)
