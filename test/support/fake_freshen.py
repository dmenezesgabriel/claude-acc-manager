"""FreshenPort fake replaying a per-account verdict map."""

from claude_acc_manager.auto.application.ports import FreshenPort, FreshenStatus


class FakeFreshen(FreshenPort):
    """Returns the scripted verdict per account (``default`` when unscripted)."""

    def __init__(
        self,
        statuses: dict[str, FreshenStatus] | None = None,
        default: FreshenStatus = "ok",
    ) -> None:
        """Script verdicts keyed by account name."""
        self._statuses = statuses or {}
        self._default = default
        self.calls: list[str] = []

    def execute(self, account_key: str) -> FreshenStatus:
        """Record the call, then replay the scripted verdict."""
        self.calls.append(account_key)
        return self._statuses.get(account_key, self._default)
