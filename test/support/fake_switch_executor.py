"""SwitchExecutorPort fake replaying a pinned SwitchResult."""

from claude_acc_manager.accounts.application.ports import (
    SwitchExecutorPort,
    SwitchResult,
)
from claude_acc_manager.accounts.domain.value_objects import AccountName


class FakeSwitchExecutor(SwitchExecutorPort):
    """Returns one pinned ``SwitchResult`` every call; records (target, dry_run)."""

    def __init__(self, result: SwitchResult) -> None:
        """Pin the outcome the transaction replays."""
        self._result = result
        self.calls: list[tuple[AccountName, bool]] = []

    def execute(self, target: AccountName, *, dry_run: bool) -> SwitchResult:
        """Record the call, then replay the pinned result."""
        self.calls.append((target, dry_run))
        return self._result
