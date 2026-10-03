"""Adapter over the credential + config files inside one account's dir.

An account dir IS the CLAUDE_CONFIG_DIR its login ran under: a scoped login
lands ``.credentials.json`` and ``.claude.json`` inside $CLAUDE_CONFIG_DIR.
So every path resolves against *account_dir* itself — no env, no home. The
config file keeps claude-code's legacy ``.config.json`` fallback via
path_resolver.global_config_in.

Two read contracts share the files: ``read_account_data`` (strict — both
files must exist; add-time capture demands a finished login) and the
AccountDirPort reads (permissive — under the switch's move model the active
account's dir legitimately holds no ``.credentials.json``).

Example:
    files = AccountDirFiles()
    creds, config = files.read_account_data(Path(".../accounts/work"))
    creds = files.read_credentials(Path(".../accounts/active-account"))
"""

from pathlib import Path

from claude_acc_manager.accounts.application.ports import (
    AccountDirPort,
    AccountDirReaderPort,
)
from claude_acc_manager.accounts.infrastructure.claude_locks import (
    storage_write_lock,
)
from claude_acc_manager.accounts.infrastructure.path_resolver import global_config_in
from claude_acc_manager.shared import fsio


class AccountDirFiles(AccountDirReaderPort, AccountDirPort):
    """Both account-dir ports over the files a scoped claude login wrote.

    Example:
        creds, config = AccountDirFiles().read_account_data(Path("/tmp/dir"))
    """

    def read_account_data(
        self,
        account_dir: Path,
    ) -> tuple[dict[str, object], dict[str, object]]:
        """Return (credentials, config); raise when a login produced no file.

        Either file missing means that login never finished — the launcher
        reported success but nothing was persisted. Torn files surface as
        ValueError from fsio.read_json_object (docs/architecture.md §8).
        """
        creds_path = account_dir / ".credentials.json"
        config_path = global_config_in(account_dir)
        if not creds_path.exists():
            raise ValueError(f"no credentials in account dir {account_dir} — login did not finish")
        if not config_path.exists():
            raise ValueError(f"no config in account dir {account_dir} — login did not finish")
        creds = fsio.read_json_object(creds_path, "credentials")
        config = fsio.read_json_object(config_path, "config")
        return creds, config

    def read_credentials(self, account_dir: Path) -> dict[str, object] | None:
        """Parse the account's credential file; ``None`` when absent."""
        path = account_dir / ".credentials.json"
        if not path.exists():
            return None
        return fsio.read_json_object(path, "credentials")

    def write_credentials(self, account_dir: Path, credentials: dict[str, object]) -> None:
        """Atomically write the credential with mode 0600."""
        with storage_write_lock(account_dir):
            fsio.atomic_write_json(account_dir / ".credentials.json", credentials)

    def delete_credentials(self, account_dir: Path) -> None:
        """Remove the account's credential file; no-op when absent."""
        with storage_write_lock(account_dir):
            (account_dir / ".credentials.json").unlink(missing_ok=True)

    def read_config(self, account_dir: Path) -> dict[str, object] | None:
        """Parse the account's resolved config; ``None`` when absent."""
        path = global_config_in(account_dir)
        if not path.exists():
            return None
        return fsio.read_json_object(path, "config")

    def write_config(self, account_dir: Path, config: dict[str, object]) -> None:
        """Atomically write the account's resolved config with mode 0600."""
        fsio.atomic_write_json(global_config_in(account_dir), config)

    def delete_config(self, account_dir: Path) -> None:
        """Remove the account's resolved config; no-op when absent."""
        global_config_in(account_dir).unlink(missing_ok=True)
