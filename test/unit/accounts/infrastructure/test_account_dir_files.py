"""Unit tests for accounts.infrastructure.account_dir_files and the
AccountDirReaderPort + AccountDirPort it implements."""

import json
import stat
from pathlib import Path

import pytest

import claude_acc_manager.accounts.infrastructure.claude_locks as claude_locks
from claude_acc_manager.accounts.application.ports import (
    AccountDirPort,
    AccountDirReaderPort,
)
from claude_acc_manager.accounts.infrastructure.account_dir_files import AccountDirFiles

FIXTURES = Path(__file__).parent / "fixtures"


def file_mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


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


class TestAccountDirFilesAdaptsThePorts:
    """AccountDirFiles explicitly subclasses both ports (greppable map)."""

    def test_files_is_an_account_dir_reader_port(self):
        # arrange / act / assert
        assert isinstance(AccountDirFiles(), AccountDirReaderPort)

    def test_files_is_an_account_dir_port(self):
        # arrange / act / assert
        assert isinstance(AccountDirFiles(), AccountDirPort)


class TestReadAccountData:
    """read_account_data parses the login files a scoped claude wrote in place."""

    def test_returns_credentials_and_config(self, tmp_path: Path):
        # arrange
        account_dir = tmp_path / "accounts" / "work"
        write_account_dir(account_dir)

        # act
        creds, config = AccountDirFiles().read_account_data(account_dir)

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
            AccountDirFiles().read_account_data(account_dir)

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
            AccountDirFiles().read_account_data(account_dir)

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
            AccountDirFiles().read_account_data(account_dir)

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
            AccountDirFiles().read_account_data(account_dir)


class TestAccountDirCredentials:
    """read/write/delete the account's own .credentials.json under move."""

    def test_read_returns_parsed_dict(self, tmp_path: Path):
        # arrange
        account_dir = tmp_path / "accounts" / "work"
        write_account_dir(account_dir)

        # act / assert
        creds = AccountDirFiles().read_credentials(account_dir)
        assert creds is not None
        assert creds["claudeAiOauth"]["accessToken"] == "tok-access-live"  # type: ignore[index]

    def test_read_returns_none_when_absent(self, tmp_path: Path):
        # arrange — under move, the ACTIVE account's dir holds no credential
        account_dir = tmp_path / "accounts" / "work"
        account_dir.mkdir(parents=True)

        # act / assert — absent is a state, not an error (unlike read_account_data)
        assert AccountDirFiles().read_credentials(account_dir) is None

    def test_read_raises_when_torn(self, tmp_path: Path):
        # arrange
        account_dir = tmp_path / "accounts" / "work"
        account_dir.mkdir(parents=True)
        (account_dir / ".credentials.json").write_text('{"broken', encoding="utf-8")

        # act / assert — the label names the credentials file (kills label mutants)
        with pytest.raises(ValueError, match=r"credentials file .*torn"):
            AccountDirFiles().read_credentials(account_dir)

    def test_write_lands_0600_and_read_round_trips(self, tmp_path: Path):
        # arrange
        account_dir = tmp_path / "accounts" / "work"
        account_dir.mkdir(parents=True)
        payload = {"claudeAiOauth": {"refreshToken": "rt"}}

        # act
        AccountDirFiles().write_credentials(account_dir, payload)

        # assert
        path = account_dir / ".credentials.json"
        assert file_mode(path) == 0o600
        assert json.loads(path.read_text(encoding="utf-8")) == payload

    def test_delete_removes_the_file(self, tmp_path: Path):
        # arrange
        account_dir = tmp_path / "accounts" / "work"
        write_account_dir(account_dir)

        # act
        AccountDirFiles().delete_credentials(account_dir)

        # assert — the credential moved out; the config stays (identity marker)
        assert not (account_dir / ".credentials.json").exists()
        assert (account_dir / ".claude.json").exists()

    def test_delete_noops_when_absent(self, tmp_path: Path):
        # arrange
        account_dir = tmp_path / "accounts" / "work"
        account_dir.mkdir(parents=True)

        # act / assert
        AccountDirFiles().delete_credentials(account_dir)
        assert AccountDirFiles().read_credentials(account_dir) is None


class TestAccountDirCredentialsHoldStorageWrite:
    """Parked .credentials.json mutations run under <account_dir>/.storage-write —
    the account dir is itself a claude secure-storage dir (it was a scoped
    CLAUDE_CONFIG_DIR at login)."""

    def test_write_and_delete_leave_no_lock_artifact(self, tmp_path: Path):
        # arrange
        account_dir = tmp_path / "accounts" / "work"
        files = AccountDirFiles()

        # act
        files.write_credentials(account_dir, {"claudeAiOauth": {}})
        files.delete_credentials(account_dir)

        # assert — the lock released cleanly both times
        assert not (account_dir / ".storage-write").exists()

    def test_write_times_out_while_the_lock_is_held(self, tmp_path: Path, monkeypatch):
        # arrange — a scoped claude is mid-mutation in this dir
        account_dir = tmp_path / "accounts" / "work"
        (account_dir / ".storage-write").mkdir(parents=True)
        monkeypatch.setattr(claude_locks, "DEFAULT_TIMEOUT_S", 0.0)
        files = AccountDirFiles()

        # act / assert
        with pytest.raises(TimeoutError):
            files.write_credentials(account_dir, {"claudeAiOauth": {}})
        assert not (account_dir / ".credentials.json").exists()

    def test_delete_times_out_while_the_lock_is_held(self, tmp_path: Path, monkeypatch):
        # arrange
        account_dir = tmp_path / "accounts" / "work"
        write_account_dir(account_dir)
        (account_dir / ".storage-write").mkdir()
        monkeypatch.setattr(claude_locks, "DEFAULT_TIMEOUT_S", 0.0)
        files = AccountDirFiles()

        # act / assert
        with pytest.raises(TimeoutError):
            files.delete_credentials(account_dir)
        assert (account_dir / ".credentials.json").exists()


class TestAccountDirConfig:
    """read/write/delete the account's own config (legacy fallback honored)."""

    def test_read_returns_parsed_dict(self, tmp_path: Path):
        # arrange
        account_dir = tmp_path / "accounts" / "work"
        write_account_dir(account_dir)

        # act / assert
        config = AccountDirFiles().read_config(account_dir)
        assert config is not None
        assert "oauthAccount" in config

    def test_read_returns_none_when_absent(self, tmp_path: Path):
        # arrange
        account_dir = tmp_path / "accounts" / "work"
        account_dir.mkdir(parents=True)

        # act / assert
        assert AccountDirFiles().read_config(account_dir) is None

    def test_read_prefers_the_legacy_config_when_both_exist(self, tmp_path: Path):
        # arrange — global_config_in reroutes to .config.json when it exists
        account_dir = tmp_path / "accounts" / "work"
        write_account_dir(account_dir)
        (account_dir / ".config.json").write_text(
            '{"oauthAccount": {"legacy": true}}', encoding="utf-8"
        )

        # act / assert
        assert AccountDirFiles().read_config(account_dir) == {"oauthAccount": {"legacy": True}}

    def test_read_raises_when_torn(self, tmp_path: Path):
        # arrange
        account_dir = tmp_path / "accounts" / "work"
        account_dir.mkdir(parents=True)
        (account_dir / ".claude.json").write_text('{"broken', encoding="utf-8")

        # act / assert — the label names the config file (kills label mutants)
        with pytest.raises(ValueError, match=r"config file .*torn"):
            AccountDirFiles().read_config(account_dir)

    def test_write_lands_0600_and_round_trips(self, tmp_path: Path):
        # arrange
        account_dir = tmp_path / "accounts" / "work"
        account_dir.mkdir(parents=True)

        # act
        AccountDirFiles().write_config(account_dir, {"oauthAccount": {"x": 1}})

        # assert
        path = account_dir / ".claude.json"
        assert file_mode(path) == 0o600
        assert AccountDirFiles().read_config(account_dir) == {"oauthAccount": {"x": 1}}

    def test_delete_removes_the_resolved_file(self, tmp_path: Path):
        # arrange
        account_dir = tmp_path / "accounts" / "work"
        write_account_dir(account_dir)

        # act
        AccountDirFiles().delete_config(account_dir)

        # assert
        assert not (account_dir / ".claude.json").exists()

    def test_delete_noops_when_absent(self, tmp_path: Path):
        # arrange
        account_dir = tmp_path / "accounts" / "work"
        account_dir.mkdir(parents=True)

        # act / assert
        AccountDirFiles().delete_config(account_dir)
        assert AccountDirFiles().read_config(account_dir) is None
