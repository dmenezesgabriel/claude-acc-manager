"""AccountDirReaderPort + AccountDirPort fake holding per-dir files in memory.

The fake models the two files inside each account's CLAUDE_CONFIG_DIR as a
map keyed by the dir path — which mirrors what use cases actually do:
``store.account_dir(name)`` hands the dir to the port. ``read_account_data``
keeps the strict both-files-present contract (add-time capture); the
AccountDirPort methods give SwitchAccount partial reads/writes/deletes.
"""

from pathlib import Path

from claude_acc_manager.accounts.application.ports import (
    AccountDirPort,
    AccountDirReaderPort,
)


class FakeAccountDir(AccountDirReaderPort, AccountDirPort):
    """Per-dir in-memory credential + config store.

    ``put`` seeds a file; an unseeded ``read_account_data`` reports a login
    that did not finish — the same ValueError the real adapter raises.
    ``read`` records the dirs ``read_account_data`` was called with.
    """

    def __init__(self) -> None:
        """Start with no files in any account dir."""
        self._creds: dict[Path, dict[str, object]] = {}
        self._configs: dict[Path, dict[str, object]] = {}
        self.read: list[Path] = []

    def put(
        self,
        account_dir: Path,
        *,
        credentials: dict[str, object] | None = None,
        config: dict[str, object] | None = None,
    ) -> None:
        """Seed *account_dir*'s files; ``None`` leaves that file absent."""
        if credentials is not None:
            self._creds[account_dir] = credentials
        if config is not None:
            self._configs[account_dir] = config

    def read_account_data(self, account_dir: Path) -> tuple[dict[str, object], dict[str, object]]:
        """Strict read for add-time capture; raise when a file is unseeded."""
        self.read.append(account_dir)
        if account_dir not in self._creds:
            raise ValueError(f"no credentials in account dir {account_dir} — login did not finish")
        if account_dir not in self._configs:
            raise ValueError(f"no config in account dir {account_dir} — login did not finish")
        return self._creds[account_dir], self._configs[account_dir]

    def read_credentials(self, account_dir: Path) -> dict[str, object] | None:
        """The seeded credentials, or ``None`` (the active account's dir)."""
        return self._creds.get(account_dir)

    def write_credentials(self, account_dir: Path, credentials: dict[str, object]) -> None:
        """Capture credentials into *account_dir*."""
        self._creds[account_dir] = credentials

    def delete_credentials(self, account_dir: Path) -> None:
        """Move-out: drop the account's credential file."""
        self._creds.pop(account_dir, None)

    def read_config(self, account_dir: Path) -> dict[str, object] | None:
        """The seeded config, or ``None``."""
        return self._configs.get(account_dir)

    def write_config(self, account_dir: Path, config: dict[str, object]) -> None:
        """Capture the config into *account_dir*."""
        self._configs[account_dir] = config

    def delete_config(self, account_dir: Path) -> None:
        """Drop the account's config file."""
        self._configs.pop(account_dir, None)
