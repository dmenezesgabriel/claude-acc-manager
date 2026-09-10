"""Unit tests for accounts.infrastructure.account_dir_reader and the
AccountDirReaderPort it implements."""

from pathlib import Path

import pytest

from claude_acc_manager.accounts.application.ports import AccountDirReaderPort
from claude_acc_manager.accounts.infrastructure.account_dir_reader import AccountDirReader

FIXTURES = Path(__file__).parent / "fixtures"


def write_account_dir(account_dir: Path) -> None:
    """Lay down the .credentials.json + .claude.json a scoped login produces."""
    account_dir.mkdir(parents=True)
    (account_dir / ".credentials.json").write_text(
        (FIXTURES / "credentials_valid.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (account_dir / ".claude.json").write_text(
        (FIXTURES / "config_valid.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )


class TestAccountDirReaderAdaptsThePort:
    """AccountDirReader explicitly subclasses the port (greppable map)."""

    def test_reader_is_an_account_dir_reader_port(self):
        # arrange / act
        reader = AccountDirReader()

        # assert
        assert isinstance(reader, AccountDirReaderPort)


class TestReadAccountData:
    """read_account_data parses the login files a scoped claude wrote in place."""

    def test_returns_credentials_and_config(self, tmp_path: Path):
        # arrange
        account_dir = tmp_path / "accounts" / "work"
        write_account_dir(account_dir)

        # act
        creds, config = AccountDirReader().read_account_data(account_dir)

        # assert
        assert creds["claudeAiOauth"]["subscriptionType"] == "pro"  # type: ignore[index]
        assert config["oauthAccount"]["emailAddress"] == "user@example.com"  # type: ignore[index]

    def test_missing_credentials_raise(self, tmp_path: Path):
        # arrange — login exited 0 but claude never wrote .credentials.json
        account_dir = tmp_path / "accounts" / "work"
        account_dir.mkdir(parents=True)
        (account_dir / ".claude.json").write_text(
            (FIXTURES / "config_valid.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        # act / assert
        with pytest.raises(ValueError, match="no credentials"):
            AccountDirReader().read_account_data(account_dir)

    def test_missing_config_raises(self, tmp_path: Path):
        # arrange
        account_dir = tmp_path / "accounts" / "work"
        account_dir.mkdir(parents=True)
        (account_dir / ".credentials.json").write_text(
            (FIXTURES / "credentials_valid.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        # act / assert
        with pytest.raises(ValueError, match="no config"):
            AccountDirReader().read_account_data(account_dir)

    def test_torn_credentials_surface_with_label(self, tmp_path: Path):
        # arrange
        account_dir = tmp_path / "accounts" / "work"
        account_dir.mkdir(parents=True)
        (account_dir / ".credentials.json").write_text(
            (FIXTURES / "credentials_torn.txt").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (account_dir / ".claude.json").write_text(
            (FIXTURES / "config_valid.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        # act / assert — the label names the failing file for triage
        with pytest.raises(ValueError, match=r"credentials file .*torn"):
            AccountDirReader().read_account_data(account_dir)

    def test_torn_config_surfaces_with_label(self, tmp_path: Path):
        # arrange
        account_dir = tmp_path / "accounts" / "work"
        account_dir.mkdir(parents=True)
        (account_dir / ".credentials.json").write_text(
            (FIXTURES / "credentials_valid.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (account_dir / ".claude.json").write_text(
            (FIXTURES / "config_torn.txt").read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        # act / assert
        with pytest.raises(ValueError, match=r"config file .*torn"):
            AccountDirReader().read_account_data(account_dir)
