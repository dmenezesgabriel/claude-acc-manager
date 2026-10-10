"""SubprocessUpgradeRunner — UpgradeRunnerPort over subprocess.run.

The upgrade runs as a child that inherits the terminal: uv/pipx progress
and any prompts reach the user, and ``check=False`` keeps a non-zero exit
as a return code the caller can report instead of a CalledProcessError.
No timeout — downloads and builds legitimately take minutes. A manager
binary absent from PATH surfaces as ``UpgradeToolMissingError`` (the
named error the command layer prints), never a raw FileNotFoundError.

Example:
    runner = SubprocessUpgradeRunner()
    rc = runner.run(["uv", "tool", "upgrade", "claude-acc-manager"])
"""

import subprocess
from collections.abc import Sequence

from claude_acc_manager.update.application.ports import (
    UpgradeRunnerPort,
    UpgradeToolMissingError,
)


class SubprocessUpgradeRunner(UpgradeRunnerPort):
    """UpgradeRunnerPort executing the manager's argv as a child process.

    Example:
        SubprocessUpgradeRunner().run(["pipx", "upgrade", "claude-acc-manager"])
    """

    def run(self, argv: Sequence[str]) -> int:
        """Run *argv* and return its exit code (port contract)."""
        try:
            completed = subprocess.run(list(argv), check=False)
        except FileNotFoundError as exc:
            raise UpgradeToolMissingError(
                f"upgrade tool {argv[0]!r} from argv {list(argv)!r} is not on PATH"
            ) from exc
        return completed.returncode
