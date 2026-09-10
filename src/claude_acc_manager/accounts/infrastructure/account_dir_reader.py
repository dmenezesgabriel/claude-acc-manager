"""Adapter that reads a captured login from one account's own config dir.

Evidence: an account dir IS the CLAUDE_CONFIG_DIR its login ran under (M0
probe 2026-09-10: a scoped login lands ``.credentials.json`` and
``.claude.json`` inside $CLAUDE_CONFIG_DIR; ai-usagebar creds.rs/cli_account.rs
read the same two files from the account dir). So the reader resolves against
*account_dir* itself — no env, no home. The config file keeps claude-code's
legacy ``.config.json`` fallback via path_resolver.global_config_in.

Example:
    reader = AccountDirReader()
    creds, config = reader.read_account_data(Path("~/.local/share/cam/accounts/work"))
"""

from pathlib import Path

from claude_acc_manager.accounts.application.ports import AccountDirReaderPort
from claude_acc_manager.accounts.infrastructure.path_resolver import global_config_in
from claude_acc_manager.shared import fsio


class AccountDirReader(AccountDirReaderPort):
    """AccountDirReaderPort over the files a scoped claude login wrote in place.

    Example:
        creds, config = AccountDirReader().read_account_data(Path("/tmp/account-dir"))
    """

    def read_account_data(
        self,
        account_dir: Path,
    ) -> tuple[dict[str, object], dict[str, object]]:
        """Return (credentials, config); raise when a login produced no file.

        Either file missing means that login never finished — the launcher
        reported success but nothing was persisted. Torn files surface as
        ValueError from fsio.read_json_object (plan §5.3).
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
