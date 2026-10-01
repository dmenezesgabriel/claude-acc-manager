"""UnclaimedCredentialPort fake recording preserves in memory."""

from pathlib import Path

from claude_acc_manager.accounts.application.ports import UnclaimedCredentialPort


class FakeUnclaimedStore(UnclaimedCredentialPort):
    """Records each preserve() call; returns a synthetic stash path.

    ``preserved`` is the assertion surface: ``(credentials, config, reason)``
    per call, in call order.
    """

    def __init__(self) -> None:
        """Start with nothing preserved."""
        self.preserved: list[tuple[dict[str, object], dict[str, object] | None, str]] = []

    def preserve(
        self,
        credentials: dict[str, object],
        config: dict[str, object] | None,
        reason: str,
    ) -> Path:
        """Record the call; return a deterministic fake path."""
        self.preserved.append((credentials, config, reason))
        return Path(f"/unclaimed/fake-{len(self.preserved)}.json")
