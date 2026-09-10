"""AccountDirReaderPort fake returning a captured login from memory."""

from pathlib import Path

from claude_acc_manager.accounts.application.ports import AccountDirReaderPort


class FakeAccountDirReader(AccountDirReaderPort):
    """Returns the pinned (credentials, config); or raises the pinned error.

    Pass *error* to simulate a login that produced no readable file (the real
    reader raises ``ValueError`` for an absent or torn file).
    """

    def __init__(
        self,
        *,
        credentials: dict[str, object] | None = None,
        config: dict[str, object] | None = None,
        error: str | None = None,
    ) -> None:
        """Pin either the data to return or the ``ValueError`` message to raise."""
        self._credentials = credentials if credentials is not None else {}
        self._config = config if config is not None else {}
        self._error = error
        self.read: list[Path] = []

    def read_account_data(self, account_dir: Path) -> tuple[dict[str, object], dict[str, object]]:
        """Record *account_dir*; raise the pinned error or return the pinned data."""
        self.read.append(account_dir)
        if self._error is not None:
            raise ValueError(self._error)
        return self._credentials, self._config
