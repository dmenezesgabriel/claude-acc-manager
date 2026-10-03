"""Unit tests for accounts.application.use_cases.add_account."""

from pathlib import Path

import pytest
from support.fake_account_dir import FakeAccountDir
from support.fake_clock import FakeClock
from support.fake_login_launcher import FakeLoginLauncher
from support.fake_ops_lock import FakeOpsLock
from support.in_memory_account_store import InMemoryAccountStore

import claude_acc_manager.accounts.infrastructure.ops_lock as ops_lock
from claude_acc_manager.accounts.application.use_cases.add_account import AddAccount
from claude_acc_manager.accounts.domain.entities import Account, QuarantineEntry
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.accounts.infrastructure.ops_lock import FlockOpsLock

_CREDENTIALS: dict[str, object] = {"claudeAiOauth": {"accessToken": "tok"}}
_CONFIG: dict[str, object] = {
    "oauthAccount": {
        "emailAddress": "user@example.com",
        "accountUuid": "acc-123",
        "organizationUuid": "org-456",
        "organizationName": "Test Org",
    },
}


def _reader(tmp_path: Path, name: str) -> FakeAccountDir:
    """A dir-fake seeded with a finished login for *name*'s account dir."""
    fake = FakeAccountDir()
    fake.put(tmp_path / "accounts" / name, credentials=_CREDENTIALS, config=_CONFIG)
    return fake


class HeldAssertingLauncher(FakeLoginLauncher):
    """Launcher recording whether the ops lock was held during ``launch``."""

    def __init__(self, ops: FakeOpsLock) -> None:
        """Start succeeding; *ops* is inspected at each launch."""
        super().__init__()
        self._ops = ops
        self.observed_held: list[bool] = []

    def launch(self, account_dir: Path) -> bool:
        """Record the ops-lock state, then behave as the base fake."""
        self.observed_held.append(self._ops.held)
        return super().launch(account_dir)


def _add_account(
    tmp_path: Path,
    *,
    launcher: FakeLoginLauncher | None = None,
    reader: FakeAccountDir | None = None,
    store: InMemoryAccountStore | None = None,
    ops: FakeOpsLock | None = None,
) -> tuple[AddAccount, InMemoryAccountStore]:
    store = store or InMemoryAccountStore(tmp_path)
    use_case = AddAccount(
        launcher or FakeLoginLauncher(),
        reader or _reader(tmp_path, "work"),
        store,
        FakeClock("2026-09-10T12:00:00Z"),
        ops or FakeOpsLock(),
    )
    return use_case, store


class TestAddAccountSuccess:
    """A completed login is captured and registered."""

    def test_launches_login_in_the_account_dir_and_registers_the_identity(self, tmp_path: Path):
        # arrange
        launcher = FakeLoginLauncher()
        reader = _reader(tmp_path, "work")
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
        reader = FakeAccountDir()
        reader.put(
            tmp_path / "accounts" / "personal",
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

    def test_re_capture_clears_a_dead_lineage_tombstone(self, tmp_path: Path):
        # arrange — "work" tombstoned after invalid_grant; re-adding captures
        # a fresh lineage, so the quarantine entry must be released
        store = InMemoryAccountStore(tmp_path)
        store.upsert(
            Account(
                name=AccountName("work"),
                email="work@example.com",
                account_uuid="acc-old",
                organization_uuid=None,
                organization_name=None,
                added_at="2026-09-10T11:00:00Z",
                enabled=True,
            )
        )
        store.set_quarantined(
            QuarantineEntry(
                name="work",
                reason="permanent_auth_error",
                at="2026-09-10T11:00:00Z",
                refresh_token_fingerprint="sha256:dead",
            )
        )
        use_case, store = _add_account(tmp_path, store=store)

        # act
        use_case.execute(AccountName("work"))

        # assert
        assert store.quarantined() == []


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
        reader = FakeAccountDir()
        reader.put(tmp_path / "accounts" / "work", credentials={"other": 1}, config=_CONFIG)
        use_case, store = _add_account(tmp_path, reader=reader)

        # act / assert
        with pytest.raises(ValueError, match="no OAuth token"):
            use_case.execute(AccountName("work"))
        assert store.list_accounts() == []

    def test_config_without_oauth_account_raises(self, tmp_path: Path):
        # arrange
        reader = FakeAccountDir()
        reader.put(
            tmp_path / "accounts" / "work",
            credentials=_CREDENTIALS,
            config={"numStartups": 1},
        )
        use_case, _ = _add_account(tmp_path, reader=reader)

        # act / assert
        with pytest.raises(ValueError, match="no oauthAccount identity"):
            use_case.execute(AccountName("work"))

    def test_an_unfinished_login_dir_reports_as_such(self, tmp_path: Path):
        # arrange — the launcher succeeded but claude wrote nothing (unseeded)
        use_case, _ = _add_account(tmp_path, reader=FakeAccountDir())

        # act / assert
        with pytest.raises(ValueError, match="login did not finish"):
            use_case.execute(AccountName("work"))


class TestAddAccountSerializes:
    """The whole add — launch through registration — runs under the store's
    ops lock, so a concurrent switch cannot move files out mid-login (the
    12:10 defect: a TUI switch moved the credential add was about to read)."""

    def test_the_login_launch_runs_inside_the_ops_lock(self, tmp_path: Path):
        # arrange
        ops = FakeOpsLock()
        launcher = HeldAssertingLauncher(ops)
        use_case, _ = _add_account(tmp_path, launcher=launcher, ops=ops)

        # act
        use_case.execute(AccountName("work"))

        # assert — the lock spanned the launch, then released
        assert launcher.observed_held == [True]
        assert ops.acquired == ["ops"]
        assert ops.held is False

    def test_registration_also_runs_inside_the_ops_lock(self, tmp_path: Path, monkeypatch):
        # arrange — the store proves the lock is still held at upsert time
        ops = FakeOpsLock()
        store = InMemoryAccountStore(tmp_path)
        observed: list[bool] = []
        base_upsert = store.upsert

        def recording_upsert(account: Account) -> None:
            observed.append(ops.held)
            base_upsert(account)

        monkeypatch.setattr(store, "upsert", recording_upsert)
        use_case, _ = _add_account(tmp_path, store=store, ops=ops)

        # act
        use_case.execute(AccountName("work"))

        # assert
        assert observed == [True]

    def test_a_held_ops_lock_refuses_the_add(self, tmp_path: Path, monkeypatch):
        # arrange — the REAL lock, held as a second cam process would hold it;
        # the add must refuse, never reaching the login
        monkeypatch.setattr(ops_lock, "DEFAULT_TIMEOUT_S", 0.0)
        ops = FlockOpsLock(tmp_path)
        store = InMemoryAccountStore(tmp_path)
        launcher = FakeLoginLauncher()
        use_case = AddAccount(
            launcher,
            _reader(tmp_path, "work"),
            store,
            FakeClock("2026-09-10T12:00:00Z"),
            ops,
        )

        # act / assert
        with ops.ops_locked(), pytest.raises(TimeoutError):
            use_case.execute(AccountName("work"))
        assert launcher.launched == []
        assert store.list_accounts() == []
