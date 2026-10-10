"""ReleaseFeedPort fake that replays a pinned version or a pinned error."""

from claude_acc_manager.update.application.ports import ReleaseFeedPort


class FakeReleaseFeed(ReleaseFeedPort):
    """Returns a pinned version (or raises a pinned error) and records calls.

    The port contract is never-raises, but a fake that CAN raise proves the
    use case keeps its own never-raises promise even against a misbehaving
    adapter.
    """

    def __init__(self, latest_version: str | None = None, error: Exception | None = None) -> None:
        """Pin the outcome — a version string to return, or an error to raise."""
        self._latest_version = latest_version
        self._error = error
        self.calls = 0

    def latest_version(self) -> str | None:
        """Record the call, then replay the pinned outcome."""
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._latest_version
