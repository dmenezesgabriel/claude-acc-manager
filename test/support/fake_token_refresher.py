"""TokenRefresherPort fake that returns a pinned result or raises a pinned error."""

from claude_acc_manager.usage.application.ports import RefreshedTokens, TokenRefresherPort


class FakeTokenRefresher(TokenRefresherPort):
    """Returns one pinned RefreshedTokens (or raises one pinned error) every call.

    Records every refresh token it was called with.
    """

    def __init__(
        self, *, refreshed: RefreshedTokens | None = None, error: Exception | None = None
    ) -> None:
        """Pin the outcome — RefreshedTokens to return, or an error to raise."""
        self._refreshed = refreshed
        self._error = error
        self.requests: list[str] = []

    def refresh(self, refresh_token: str) -> RefreshedTokens:
        """Record the call, then replay the pinned result or error."""
        self.requests.append(refresh_token)
        if self._error is not None:
            raise self._error
        assert self._refreshed is not None, "FakeTokenRefresher has no scripted result"
        return self._refreshed
