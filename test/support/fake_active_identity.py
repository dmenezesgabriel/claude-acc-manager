"""ActiveIdentityPort fake that replays a pinned live-slot status."""

from claude_acc_manager.accounts.application.ports import (
    ActiveAccountStatus,
    ActiveIdentityPort,
)


class FakeActiveIdentity(ActiveIdentityPort):
    """Returns one pinned ``ActiveAccountStatus`` (or ``None``) every call."""

    def __init__(self, status: ActiveAccountStatus | None) -> None:
        """Pin the live-slot resolution."""
        self._status = status
        self.calls = 0

    def execute(self) -> ActiveAccountStatus | None:
        """Record the call, then replay the pinned status."""
        self.calls += 1
        return self._status
