"""UsageApiPort fake that returns a pinned snapshot or raises a pinned error."""

from claude_acc_manager.usage.application.ports import UsageApiPort
from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot


class FakeUsageApi(UsageApiPort):
    """Returns one pinned UsageSnapshot (or raises one pinned error) every call.

    Records every access token it was called with so tests can assert what
    credential the use case actually sent.
    """

    def __init__(
        self, *, snapshot: UsageSnapshot | None = None, error: Exception | None = None
    ) -> None:
        """Pin the outcome — a UsageSnapshot to return, or an error to raise."""
        self._snapshot = snapshot
        self._error = error
        self.requests: list[str] = []

    def fetch_usage(self, access_token: str) -> UsageSnapshot:
        """Record the call, then replay the pinned snapshot or error."""
        self.requests.append(access_token)
        if self._error is not None:
            raise self._error
        assert self._snapshot is not None, "FakeUsageApi has no scripted snapshot"
        return self._snapshot
