"""UpgradeRunnerPort fake that records argv and replays a pinned exit code."""

from collections.abc import Sequence

from claude_acc_manager.update.application.ports import UpgradeRunnerPort


class FakeUpgradeRunner(UpgradeRunnerPort):
    """Records every argv in order, then returns a pinned rc or raises."""

    def __init__(self, returncode: int = 0, error: Exception | None = None) -> None:
        """Pin the outcome — an exit code to return, or an error to raise."""
        self._returncode = returncode
        self._error = error
        self.calls: list[list[str]] = []

    def run(self, argv: Sequence[str]) -> int:
        """Record the call, then replay the pinned outcome."""
        self.calls.append(list(argv))
        if self._error is not None:
            raise self._error
        return self._returncode
