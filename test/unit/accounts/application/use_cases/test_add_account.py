"""Unit tests for accounts.application.use_cases.add_account."""

from pathlib import Path

import pytest
from support.fake_account_dir_reader import FakeAccountDirReader
from support.fake_clock import FakeClock
from support.fake_login_launcher import FakeLoginLauncher
from support.in_memory_account_store import InMemoryAccountStore

from claude_acc_manager.accounts.application.use_cases.add_account import AddAccount
from claude_acc_manager.accounts.domain.value_objects import AccountName

_CREDENTIALS: dict[str, object] = {"claudeAiOauth": {"accessToken": "tok"}}
_CONFIG: dict[str, object] = {
    "oauthAccount": {
        "emailAddress": "user@example.com",
        "accountUuid": "acc-123",
        "organizationUuid": "org-456",
        "organizationName": "Test Org",
    },
}


def _add_account(
    tmp_path: Path,
    *,
    launcher: FakeLoginLauncher | None = None,
    reader: FakeAccountDirReader | None = None,
    store: InMemoryAccountStore | None = None,
) -> tuple[AddAccount, InMemoryAccountStore]:
    store = store or InMemoryAccountStore(tmp_path)
    use_case = AddAccount(
        launcher or FakeLoginLauncher(),
        reader or FakeAccountDirReader(credentials=_CREDENTIALS, config=_CONFIG),
        store,
        FakeClock("2026-09-10T12:00:00Z"),
    )
    return use_case, store


class TestAddAccountSuccess:
    """A completed login is captured and registered."""

    def test_launches_login_in_the_account_dir_and_registers_the_identity(self, tmp_path: Path):
        # arrange
        launcher = FakeLoginLauncher()
        reader = FakeAccountDirReader(credentials=_CREDENTIALS, config=_CONFIG)
        use_case, store = _add_account(tmp_path, launcher=launcher, reader=reader)

        # act
        use_case.execute(AccountName("work"))

        # assert
        assert launcher.launched == [tmp_path / "accounts" / "work"]
        assert reader.read == [tmp_path / "accounts" / "work"]
        account = store.get(AccountName("work"))
        assert account is not None
        assert account.email == "user@example.com"
        assert account.account_uuid == "acc-123"
        assert account.organization_uuid == "org-456"
        assert account.organization_name == "Test Org"
        assert account.added_at == "2026-09-10T12:00:00Z"
        assert account.enabled is True

    def test_creates_the_account_dir_private_before_launching(self, tmp_path: Path):
        # arrange
        use_case, _ = _add_account(tmp_path)

        # act
        use_case.execute(AccountName("work"))

        # assert
        account_dir = tmp_path / "accounts" / "work"
        assert account_dir.is_dir()
        assert (account_dir.stat().st_mode & 0o777) == 0o700

    def test_missing_optional_org_fields_are_stored_as_none(self, tmp_path: Path):
        # arrange
        reader = FakeAccountDirReader(
            credentials=_CREDENTIALS,
            config={"oauthAccount": {"emailAddress": "u@e.com", "accountUuid": "acc-1"}},
        )
        use_case, store = _add_account(tmp_path, reader=reader)

        # act
        use_case.execute(AccountName("personal"))

        # assert
        account = store.get(AccountName("personal"))
        assert account is not None
        assert account.organization_uuid is None
        assert account.organization_name is None

    def test_re_adding_replaces_without_duplicating_the_order_entry(self, tmp_path: Path):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        use_case, _ = _add_account(tmp_path, store=store)
        use_case.execute(AccountName("work"))

        # act
        use_case.execute(AccountName("work"))

        # assert
        assert [a.name.value for a in store.list_accounts()] == ["work"]


class TestAddAccountFailure:
    """A login that did not finish or captured nothing usable fails loudly and
    registers no account."""

    def test_launcher_failure_raises_and_registers_nothing(self, tmp_path: Path):
        # arrange
        use_case, store = _add_account(tmp_path, launcher=FakeLoginLauncher(succeeds=False))

        # act / assert
        with pytest.raises(ValueError, match="did not complete"):
            use_case.execute(AccountName("work"))
        assert store.list_accounts() == []

    def test_credentials_without_oauth_token_raise(self, tmp_path: Path):
        # arrange
        reader = FakeAccountDirReader(credentials={"other": 1}, config=_CONFIG)
        use_case, store = _add_account(tmp_path, reader=reader)

        # act / assert
        with pytest.raises(ValueError, match="no OAuth token"):
            use_case.execute(AccountName("work"))
        assert store.list_accounts() == []

    def test_config_without_oauth_account_raises(self, tmp_path: Path):
        # arrange
        reader = FakeAccountDirReader(credentials=_CREDENTIALS, config={"numStartups": 1})
        use_case, _ = _add_account(tmp_path, reader=reader)

        # act / assert
        with pytest.raises(ValueError, match="no oauthAccount identity"):
            use_case.execute(AccountName("work"))

    def test_reader_error_propagates(self, tmp_path: Path):
        # arrange
        reader = FakeAccountDirReader(error="no credentials in account dir — login did not finish")
        use_case, _ = _add_account(tmp_path, reader=reader)

        # act / assert
        with pytest.raises(ValueError, match="login did not finish"):
            use_case.execute(AccountName("work"))
