"""Unit tests for the cam CLI (add / remove / list / status).

User-facing output is pinned exactly — the printed line *is* the interface
(docs/architecture.md §10), so a drift in wording is a regression, not cosmetic.
"""

from dataclasses import replace
from pathlib import Path

import pytest
from support.controllable_clock import ControllableClock
from support.fake_account_dir import FakeAccountDir
from support.fake_active_slot import FakeActiveSlot
from support.fake_claude_locks import FakeClaudeLocks
from support.fake_clock import FakeClock
from support.fake_credential_store import FakeCredentialStore
from support.fake_login_launcher import FakeLoginLauncher
from support.fake_token_refresher import FakeTokenRefresher
from support.fake_unclaimed_store import FakeUnclaimedStore
from support.fake_usage_api import FakeUsageApi
from support.in_memory_account_store import InMemoryAccountStore
from support.in_memory_usage_cache import InMemoryUsageCache

from claude_acc_manager.accounts.application.use_cases.add_account import AddAccount
from claude_acc_manager.accounts.application.use_cases.list_accounts import ListAccounts
from claude_acc_manager.accounts.application.use_cases.quarantine_account import (
    QuarantineAccount,
)
from claude_acc_manager.accounts.application.use_cases.remove_account import RemoveAccount
from claude_acc_manager.accounts.application.use_cases.set_account_enabled import (
    SetAccountEnabled,
)
from claude_acc_manager.accounts.application.use_cases.status_account import StatusAccount
from claude_acc_manager.accounts.application.use_cases.switch_account import SwitchAccount
from claude_acc_manager.accounts.domain.credential_fields import refresh_token_fingerprint
from claude_acc_manager.accounts.domain.entities import Account
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.cli import ProcessContext, UseCases, run
from claude_acc_manager.usage.application.ports import AnthropicApiError, RefreshedTokens
from claude_acc_manager.usage.application.use_cases.fetch_account_usage import FetchAccountUsage
from claude_acc_manager.usage.domain.oauth_credential import StoredOAuthCredential
from claude_acc_manager.usage.domain.usage_cache_entry import EMPTY_USAGE_CACHE_ENTRY
from claude_acc_manager.usage.domain.usage_snapshot import ScopedWindow, UsageSnapshot, UsageWindow

_CREDENTIALS: dict[str, object] = {"claudeAiOauth": {"accessToken": "tok"}}
_CONFIG: dict[str, object] = {
    "oauthAccount": {"emailAddress": "user@example.com", "accountUuid": "acc-123"},
}
_USAGE_SNAPSHOT = UsageSnapshot(
    five_hour=UsageWindow(pct=10.0, resets_at=None), seven_day=None, scoped=()
)


def _use_cases(
    tmp_path: Path,
    *,
    store: InMemoryAccountStore | None = None,
    launcher: FakeLoginLauncher | None = None,
    reader: FakeAccountDir | None = None,
    slot: FakeActiveSlot | None = None,
    fetch_usage: FetchAccountUsage | None = None,
    usage_cache: InMemoryUsageCache | None = None,
) -> UseCases:
    store = store or InMemoryAccountStore(tmp_path)
    slot = slot or FakeActiveSlot(config=None)
    if reader is None:
        reader = FakeAccountDir()
        reader.put(tmp_path / "accounts" / "work", credentials=_CREDENTIALS, config=_CONFIG)
    clock = FakeClock()
    return UseCases(
        add=AddAccount(launcher or FakeLoginLauncher(), reader, store, clock),
        remove=RemoveAccount(store),
        list_accounts=ListAccounts(store),
        status=StatusAccount(slot, store),
        fetch_usage=fetch_usage or _fetch_usage(),
        switch=SwitchAccount(store, slot, reader, FakeUnclaimedStore(), FakeClaudeLocks(), clock),
        quarantine=QuarantineAccount(store, clock),
        set_enabled=SetAccountEnabled(store),
        account_store=store,
        account_files=reader,
        usage_cache=usage_cache or InMemoryUsageCache(),
    )


def _fetch_usage(
    *,
    usage_api: FakeUsageApi | None = None,
    refresher: FakeTokenRefresher | None = None,
    credentials: FakeCredentialStore | None = None,
) -> FetchAccountUsage:
    return FetchAccountUsage(
        usage_api or FakeUsageApi(snapshot=_USAGE_SNAPSHOT),
        refresher or FakeTokenRefresher(),
        credentials or FakeCredentialStore(),
        InMemoryUsageCache(),
        ControllableClock(now_epoch_s=1_000_000.0),
    )


def _run(argv: list[str], use_cases: UseCases) -> int:
    """Dispatch under a non-root, non-container process context."""
    return run(argv, use_cases, process=ProcessContext(euid=1000, in_container=False))


def _account(name: str, account_uuid: str = "acc-x") -> Account:
    return Account(
        name=AccountName(name),
        email=f"{name}@example.com",
        account_uuid=account_uuid,
        organization_uuid=None,
        organization_name=None,
        added_at="2026-09-10T12:00:00Z",
        enabled=True,
    )


def _creds_for(name: str) -> dict[str, object]:
    return {"claudeAiOauth": {"accessToken": f"at-{name}", "refreshToken": f"rt-{name}"}}


def _config_for(account_uuid: str) -> dict[str, object]:
    return {"oauthAccount": {"emailAddress": "user@example.com", "accountUuid": account_uuid}}


class TestAddCommand:
    def test_add_registers_the_account_and_prints_confirmation(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        store = InMemoryAccountStore(tmp_path)

        # act
        code = _run(["add", "work"], _use_cases(tmp_path, store=store))

        # assert
        assert code == 0
        assert store.get(AccountName("work")) is not None
        assert capsys.readouterr().out == "added account 'work'\n"

    def test_add_failure_prints_the_error_to_stderr_and_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        use_cases = _use_cases(tmp_path, launcher=FakeLoginLauncher(succeeds=False))

        # act
        code = _run(["add", "work"], use_cases)

        # assert
        captured = capsys.readouterr()
        assert code == 1
        assert captured.out == ""
        assert captured.err == "error: claude login did not complete for account 'work'\n"


class TestRemoveCommand:
    def test_remove_deletes_the_account_and_prints_confirmation(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))

        # act
        code = _run(["remove", "work"], _use_cases(tmp_path, store=store))

        # assert
        assert code == 0
        assert store.get(AccountName("work")) is None
        assert capsys.readouterr().out == "removed account 'work'\n"

    def test_remove_unknown_account_prints_a_named_error_and_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = _run(["remove", "ghost"], _use_cases(tmp_path))

        # assert
        assert code == 1
        assert capsys.readouterr().err == "error: no such account: 'ghost'\n"


class TestListCommand:
    def test_empty_store_prints_a_placeholder(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = _run(["list"], _use_cases(tmp_path))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "no accounts registered\n"

    def test_lists_accounts_in_order_marking_the_active_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        store.upsert(_account("personal"))
        store.set_active(AccountName("work"))

        # act
        code = _run(["list"], _use_cases(tmp_path, store=store))

        # assert
        assert code == 0
        assert capsys.readouterr().out == (
            "* work\twork@example.com\n  personal\tpersonal@example.com\n"
        )


class TestStatusCommand:
    def test_no_login_prints_a_placeholder(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = _run(["status"], _use_cases(tmp_path))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "no account is logged in\n"

    def test_managed_login_names_the_registry_account(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work", account_uuid="acc-123"))
        slot = FakeActiveSlot(config=_CONFIG)

        # act
        code = _run(["status"], _use_cases(tmp_path, store=store, slot=slot))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "logged in as user@example.com (managed as 'work')\n"

    def test_unmanaged_login_is_reported_as_such(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        slot = FakeActiveSlot(config=_CONFIG)

        # act
        code = _run(["status"], _use_cases(tmp_path, slot=slot))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "logged in as user@example.com (not managed)\n"


class TestUsageCommand:
    def test_unknown_account_prints_a_named_error_and_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = _run(["usage", "ghost"], _use_cases(tmp_path))

        # assert
        assert code == 1
        assert capsys.readouterr().err == "error: no such account: 'ghost'\n"

    def test_prints_the_fetched_usage(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        snapshot = UsageSnapshot(
            five_hour=UsageWindow(pct=62.0, resets_at=None),
            seven_day=UsageWindow(pct=27.0, resets_at=None),
            scoped=(),
        )
        credentials = FakeCredentialStore(credentials={"work": _stored_credential()})
        fetch_usage = _fetch_usage(
            usage_api=FakeUsageApi(snapshot=snapshot), credentials=credentials
        )

        # act
        code = _run(["usage", "work"], _use_cases(tmp_path, store=store, fetch_usage=fetch_usage))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "five_hour: 62%\nseven_day: 27%\n"

    def test_prints_a_scoped_model_window(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        snapshot = UsageSnapshot(
            five_hour=None, seven_day=None, scoped=(ScopedWindow("Fable", 84.0, None),)
        )
        credentials = FakeCredentialStore(credentials={"work": _stored_credential()})
        fetch_usage = _fetch_usage(
            usage_api=FakeUsageApi(snapshot=snapshot), credentials=credentials
        )

        # act
        code = _run(["usage", "work"], _use_cases(tmp_path, store=store, fetch_usage=fetch_usage))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "Fable: 84%\n"

    def test_prints_a_stale_note_when_serving_last_good(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — a frozen last_good served after a 429
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(EMPTY_USAGE_CACHE_ENTRY, last_good=_USAGE_SNAPSHOT, fetched_at_s=999_800.0),
        )
        credentials = FakeCredentialStore(credentials={"work": _stored_credential()})
        fetch_usage = FetchAccountUsage(
            FakeUsageApi(error=AnthropicApiError(429, None)),
            FakeTokenRefresher(),
            credentials,
            cache,
            ControllableClock(now_epoch_s=1_000_000.0),
        )

        # act
        code = _run(["usage", "work"], _use_cases(tmp_path, store=store, fetch_usage=fetch_usage))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "five_hour: 10%\n(stale: http-429)\n"

    def test_reports_unknown_when_nothing_is_known(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — no credential captured, so the fetch has nothing to serve
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        fetch_usage = _fetch_usage(credentials=FakeCredentialStore())

        # act
        code = _run(["usage", "work"], _use_cases(tmp_path, store=store, fetch_usage=fetch_usage))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "usage unknown: no-credential\n"

    def test_the_active_account_is_never_refreshed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — an expired token on the LIVE account must not refresh
        # (ADR-0009: Claude Code owns the active slot's tokens; the live
        # config's accountUuid, not the registry pointer, resolves "active")
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        slot = FakeActiveSlot(credentials=_CREDENTIALS, config=_config_for("acc-x"))
        credentials = FakeCredentialStore(
            credentials={"work": _stored_credential(expires_at_ms=0.0)}
        )
        refresher = FakeTokenRefresher()
        fetch_usage = _fetch_usage(credentials=credentials, refresher=refresher)

        # act
        _run(
            ["usage", "work"],
            _use_cases(tmp_path, store=store, slot=slot, fetch_usage=fetch_usage),
        )

        # assert
        assert refresher.requests == []

    def test_a_pointer_active_but_live_foreign_account_still_refreshes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — the pointer says "work" but the live slot belongs to an
        # unmanaged login: "work" is parked, so its expired token refreshes
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        store.set_active(AccountName("work"))
        slot = FakeActiveSlot(credentials=_CREDENTIALS, config=_config_for("acc-foreign"))
        credentials = FakeCredentialStore(
            credentials={"work": _stored_credential(expires_at_ms=0.0)}
        )
        refresher = FakeTokenRefresher(
            refreshed=RefreshedTokens(
                access_token="at-new", refresh_token="rt-new", expires_in_s=3600.0
            )
        )
        fetch_usage = _fetch_usage(credentials=credentials, refresher=refresher)

        # act
        _run(
            ["usage", "work"],
            _use_cases(tmp_path, store=store, slot=slot, fetch_usage=fetch_usage),
        )

        # assert
        assert refresher.requests == ["rt-old"]

    def test_permanent_auth_error_quarantines_the_dead_lineage(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — the parked account's expired token gets invalid_grant
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        reader = FakeAccountDir()
        parked = {"claudeAiOauth": {"accessToken": "at", "refreshToken": "rt-dead"}}
        reader.put(
            store.account_dir(AccountName("work")),
            credentials=parked,
            config=_config_for("acc-x"),
        )
        credentials = FakeCredentialStore(
            credentials={"work": _stored_credential(expires_at_ms=0.0)}
        )
        fetch_usage = _fetch_usage(
            credentials=credentials,
            refresher=FakeTokenRefresher(error=AnthropicApiError(400, "invalid_grant")),
        )

        # act
        code = _run(
            ["usage", "work"],
            _use_cases(tmp_path, store=store, reader=reader, fetch_usage=fetch_usage),
        )

        # assert — the tombstone binds the dead lineage by refresh-token fingerprint
        assert code == 0
        (entry,) = store.quarantined()
        assert entry.name == "work"
        assert entry.reason == "permanent_auth_error"
        assert entry.refresh_token_fingerprint == refresh_token_fingerprint(parked)
        assert capsys.readouterr().out == (
            "usage unknown: invalid_grant\n"
            "quarantined 'work': the provider permanently rejected its refresh token\n"
        )

    def test_permanent_auth_error_with_no_parked_file_tombstones_unfingerprinted(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — the lineage failed but its parked file is already gone;
        # the tombstone still binds the name with a None fingerprint
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        reader = FakeAccountDir()
        credentials = FakeCredentialStore(
            credentials={"work": _stored_credential(expires_at_ms=0.0)}
        )
        fetch_usage = _fetch_usage(
            credentials=credentials,
            refresher=FakeTokenRefresher(error=AnthropicApiError(400, "invalid_grant")),
        )

        # act
        code = _run(
            ["usage", "work"],
            _use_cases(tmp_path, store=store, reader=reader, fetch_usage=fetch_usage),
        )

        # assert
        assert code == 0
        (entry,) = store.quarantined()
        assert entry.name == "work"
        assert entry.refresh_token_fingerprint is None

    def test_an_inactive_account_refreshes_an_expired_token(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — same expired credential, but the account isn't active
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        credentials = FakeCredentialStore(
            credentials={"work": _stored_credential(expires_at_ms=0.0)}
        )
        refresher = FakeTokenRefresher(
            refreshed=RefreshedTokens(
                access_token="at-new", refresh_token="rt-new", expires_in_s=3600.0
            )
        )
        fetch_usage = _fetch_usage(credentials=credentials, refresher=refresher)

        # act
        _run(["usage", "work"], _use_cases(tmp_path, store=store, fetch_usage=fetch_usage))

        # assert
        assert refresher.requests == ["rt-old"]


def _stored_credential(*, expires_at_ms: float | None = None) -> StoredOAuthCredential:
    return StoredOAuthCredential(
        access_token="at-old", refresh_token="rt-old", expires_at_ms=expires_at_ms
    )


class TestArgParsing:
    def test_no_subcommand_prints_usage_to_stderr_and_exits_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = _run([], _use_cases(tmp_path))

        # assert
        assert code == 2
        assert capsys.readouterr().err == (
            "usage: cam [-h] {add,remove,list,status,usage,switch,disable,enable} ...\n"
        )

    def test_rejects_a_flag_shaped_account_name(self, tmp_path: Path):
        # act / assert — argparse treats it as an unknown option
        with pytest.raises(SystemExit):
            _run(["add", "--sneaky"], _use_cases(tmp_path))


class TestRootGuard:
    """euid 0 outside a container is refused before dispatch (§8.6).

    Reference: claude-swap cli.py _guard_root — the check runs after parsing
    (so --help still works) and before the handler runs (the refusal gates
    command execution, not the no-command usage print).
    """

    def test_root_outside_a_container_is_refused(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = run(
            ["list"],
            _use_cases(tmp_path),
            process=ProcessContext(euid=0, in_container=False),
        )

        # assert
        assert code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == "error: refusing to run as root (outside a container)\n"

    def test_root_inside_a_container_is_allowed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = run(
            ["list"],
            _use_cases(tmp_path),
            process=ProcessContext(euid=0, in_container=True),
        )

        # assert
        assert code == 0
        assert capsys.readouterr().out == "no accounts registered\n"

    def test_no_subcommand_as_root_prints_usage_not_a_refusal(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act — bare cam never dispatches, so the guard doesn't fire
        code = run([], _use_cases(tmp_path), process=ProcessContext(euid=0, in_container=False))

        # assert
        assert code == 2
        assert "usage:" in capsys.readouterr().err


class TestEnableDisableCommands:
    """cam disable/enable — ports claude-swap set_account_disabled's notices.

    Enabled only gates *automatic* picks; a disabled account stays a valid
    explicit ``cam switch <name>`` target (SetAccountEnabled, M6).
    """

    def test_disable_marks_the_account_and_confirms(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — x is enabled but not active; y keeps rotation non-empty
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("x"))
        store.upsert(_account("y"))

        # act
        code = _run(["disable", "x"], _use_cases(tmp_path, store=store))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "disabled account 'x'\n"
        account = store.get(AccountName("x"))
        assert account is not None and not account.enabled

    def test_disable_unknown_account_errors(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = _run(["disable", "ghost"], _use_cases(tmp_path))

        # assert
        assert code == 1
        assert capsys.readouterr().err == "error: no such account: 'ghost'\n"

    def test_disable_an_already_disabled_account_is_a_quiet_noop(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("x"))
        store.set_enabled(AccountName("x"), False)

        # act
        code = _run(["disable", "x"], _use_cases(tmp_path, store=store))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "account 'x' is already disabled\n"

    def test_disable_the_active_account_notes_it_stays_live(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — x is the registry's active account; another stays enabled
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("x"))
        store.upsert(_account("y"))
        store.set_active(AccountName("x"))

        # act
        code = _run(["disable", "x"], _use_cases(tmp_path, store=store))

        # assert
        assert code == 0
        assert capsys.readouterr().out == (
            "disabled account 'x'\n"
            "  note: 'x' is the active account — it stays live until you "
            "switch away; it just won't be an automatic switch target\n"
        )

    def test_disable_the_last_enabled_account_warns_rotation_is_empty(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — x is the only enabled account left (y already disabled)
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("x"))
        store.upsert(_account("y"))
        store.set_enabled(AccountName("y"), False)

        # act
        code = _run(["disable", "x"], _use_cases(tmp_path, store=store))

        # assert
        assert code == 0
        assert capsys.readouterr().out == (
            "disabled account 'x'\n"
            "  warning: no enabled accounts remain in rotation — automatic "
            "switching has nothing to pick (re-enable one with cam enable <name>)\n"
        )

    def test_enable_returns_the_account_to_rotation(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("x"))
        store.set_enabled(AccountName("x"), False)

        # act
        code = _run(["enable", "x"], _use_cases(tmp_path, store=store))

        # assert
        assert code == 0
        assert capsys.readouterr().out == ("enabled account 'x'\n  it is back in the rotation\n")
        account = store.get(AccountName("x"))
        assert account is not None and account.enabled

    def test_enable_an_already_enabled_account_is_a_quiet_noop(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("x"))

        # act
        code = _run(["enable", "x"], _use_cases(tmp_path, store=store))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "account 'x' is already enabled\n"


class TestHelpText:
    """--help output describes every command; the phrasing is pinned."""

    def _help(self, tmp_path: Path, capsys: pytest.CaptureFixture[str], *argv: str) -> str:
        with pytest.raises(SystemExit):
            _run([*argv, "--help"], _use_cases(tmp_path))
        return capsys.readouterr().out

    def test_top_level_help_lists_the_prog_description_and_commands(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        text = self._help(tmp_path, capsys)

        # assert
        assert text.startswith(
            "usage: cam [-h] {add,remove,list,status,usage,switch,disable,enable} ...\n"
        )
        assert "\nmanage Claude Code OAuth accounts\n" in text
        assert "    add                 register an account via an isolated claude login\n" in text
        assert "    remove              unregister an account and delete its login dir\n" in text
        assert "    list                list registered accounts\n" in text
        assert "    status              show the account the live claude slot uses\n" in text
        assert "    disable             hold an account out of automatic switching\n" in text
        assert "    enable              return a disabled account to automatic switching\n" in text
        assert "    usage               show one account's quota usage\n" in text
        assert "    switch              move the live claude login to another account\n" in text

    def test_add_and_remove_help_document_the_name_argument(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act / assert
        for command in ("add", "remove", "usage", "disable", "enable"):
            text = self._help(tmp_path, capsys, command)
            assert text.startswith(f"usage: cam {command} [-h] name\n")
            assert "  name        account name\n" in text


def _park(store: InMemoryAccountStore, reader: FakeAccountDir, name: str) -> None:
    """Register *name* with its credential parked in its account dir."""
    store.upsert(_account(name, account_uuid=f"acc-{name}"))
    reader.put(
        store.account_dir(AccountName(name)),
        credentials=_creds_for(name),
        config=_config_for(f"acc-{name}"),
    )


def _cache_usage(cache: InMemoryUsageCache, name: str, pct: float) -> None:
    """Seed one account's cached usage snapshot (pct = percent used)."""
    snapshot = UsageSnapshot(
        five_hour=UsageWindow(pct=pct, resets_at=None), seven_day=None, scoped=()
    )
    cache.save(name, replace(EMPTY_USAGE_CACHE_ENTRY, last_good=snapshot))


class TestSwitchCommand:
    def test_switches_to_the_named_account(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — x live, y parked
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))

        # act
        code = _run(["switch", "y"], _use_cases(tmp_path, store=store, reader=reader, slot=slot))

        # assert — the move model: y's lineage now lives in the live slot
        assert code == 0
        assert capsys.readouterr().out == "switched to 'y' (was 'x')\n"
        assert slot.read_credentials() == _creds_for("y")
        y_dir = store.account_dir(AccountName("y"))
        x_dir = store.account_dir(AccountName("x"))
        assert reader.read_credentials(y_dir) is None
        assert reader.read_credentials(x_dir) == _creds_for("x")
        active = store.active()
        assert active is not None and active.name.value == "y"

    def test_unknown_target_prints_a_named_error_and_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = _run(["switch", "ghost"], _use_cases(tmp_path))

        # assert
        assert code == 1
        assert capsys.readouterr().err == "error: no such account: 'ghost'\n"

    def test_a_target_and_a_strategy_together_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "y")

        # act
        code = _run(
            ["switch", "y", "--strategy", "best"],
            _use_cases(tmp_path, store=store, reader=reader),
        )

        # assert
        assert code == 1
        assert "cannot combine an explicit target 'y' with strategy 'best'" in (
            capsys.readouterr().err
        )

    def test_bare_switch_rotates_to_the_next_registered_account(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — x live, y parked after it in registry order
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))

        # act
        code = _run(["switch"], _use_cases(tmp_path, store=store, reader=reader, slot=slot))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "switched to 'y' (was 'x')\n"

    def test_best_strategy_picks_the_roomiest_measured_candidate(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — x live at 80% used; y at 90%, z at 30%
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        _park(store, reader, "z")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))
        cache = InMemoryUsageCache()
        _cache_usage(cache, "x", 80.0)
        _cache_usage(cache, "y", 90.0)
        _cache_usage(cache, "z", 30.0)

        # act
        code = _run(
            ["switch", "--strategy", "best"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot, usage_cache=cache),
        )

        # assert
        assert code == 0
        assert capsys.readouterr().out == "switched to 'z' (was 'x')\n"

    def test_next_available_skips_an_exhausted_candidate(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — y is at its limit (0 headroom); z still has room
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        _park(store, reader, "z")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))
        cache = InMemoryUsageCache()
        _cache_usage(cache, "y", 100.0)
        _cache_usage(cache, "z", 30.0)

        # act
        code = _run(
            ["switch", "--strategy", "next-available"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot, usage_cache=cache),
        )

        # assert
        assert code == 0
        assert capsys.readouterr().out == ("switched to 'z' (was 'x')\nskipped 'y': at-limit\n")

    def test_dry_run_reports_the_plan_without_moving_anything(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))

        # act
        code = _run(
            ["switch", "y", "--dry-run"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot),
        )

        # assert — nothing moved
        assert code == 0
        assert capsys.readouterr().out == "dry run: switched to 'y' (was 'x')\n"
        assert slot.read_credentials() == _creds_for("x")
        y_dir = store.account_dir(AccountName("y"))
        assert reader.read_credentials(y_dir) == _creds_for("y")
        active = store.active()
        assert active is not None and active.name.value == "x"

    def test_an_unmanaged_live_login_is_preserved(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — the live slot holds a foreign login, not a managed account
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        slot = FakeActiveSlot(credentials=_creds_for("foreign"), config=_config_for("acc-foreign"))

        # act
        code = _run(["switch", "x"], _use_cases(tmp_path, store=store, reader=reader, slot=slot))

        # assert
        assert code == 0
        assert capsys.readouterr().out == (
            "switched to 'x' (was an unmanaged login)\n"
            "the previous unmanaged login was preserved under /unclaimed/fake-1.json\n"
        )

    def test_switching_to_the_live_account_reports_already_active(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))

        # act
        code = _run(["switch", "x"], _use_cases(tmp_path, store=store, reader=reader, slot=slot))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "'x' is already the active account\n"

    def test_a_scoped_shell_is_refused_with_an_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — `cam` inside CLAUDE_CONFIG_DIR=accounts/x resolves "live"
        # to x's parked dir
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        scoped = store.account_dir(AccountName("x")) / ".credentials.json"
        slot = FakeActiveSlot(
            credentials=_creds_for("x"),
            config=_config_for("acc-x"),
            live_credentials_path=scoped,
        )

        # act
        code = _run(["switch", "y"], _use_cases(tmp_path, store=store, reader=reader, slot=slot))

        # assert
        assert code == 1
        assert "scoped shell" in capsys.readouterr().err

    def test_model_flag_is_accepted(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange — --model is parsed for parity; settings persistence is M9
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))

        # act
        code = _run(
            ["switch", "y", "--model", "claude-opus-4"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot),
        )

        # assert
        assert code == 0
        assert capsys.readouterr().out == "switched to 'y' (was 'x')\n"

    def test_candidates_exhausted_reports_the_stay(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — every candidate measured at its limit
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))
        cache = InMemoryUsageCache()
        _cache_usage(cache, "y", 100.0)

        # act
        code = _run(
            ["switch", "--strategy", "next-available"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot, usage_cache=cache),
        )

        # assert
        assert code == 0
        assert capsys.readouterr().out == (
            "every candidate is at its limit\nskipped 'y': at-limit\n"
        )

    def test_no_valid_target_reports_the_stay(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — x live, the only other account disabled
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        store.set_enabled(AccountName("y"), False)
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))

        # act
        code = _run(["switch"], _use_cases(tmp_path, store=store, reader=reader, slot=slot))

        # assert
        assert code == 0
        assert capsys.readouterr().out == ("no valid switch target\nskipped 'y': disabled\n")

    def test_best_without_a_current_measurement_reports_usage_unavailable(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — the live account was never measured, so no candidate can
        # provably beat it
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))
        cache = InMemoryUsageCache()
        _cache_usage(cache, "y", 10.0)

        # act
        code = _run(
            ["switch", "--strategy", "best"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot, usage_cache=cache),
        )

        # assert
        assert code == 0
        assert capsys.readouterr().out == "usage unknown — cannot rank candidates\n"

    def test_best_when_the_live_account_already_leads_reports_already_best(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — x live at 10% used, y at 90%
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))
        cache = InMemoryUsageCache()
        _cache_usage(cache, "x", 10.0)
        _cache_usage(cache, "y", 90.0)

        # act
        code = _run(
            ["switch", "--strategy", "best"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot, usage_cache=cache),
        )

        # assert
        assert code == 0
        assert capsys.readouterr().out == ("the active account already has the most headroom\n")

    def test_switch_with_no_prior_login_reports_no_login(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — the live slot is empty; x is parked
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        slot = FakeActiveSlot()

        # act
        code = _run(["switch", "x"], _use_cases(tmp_path, store=store, reader=reader, slot=slot))

        # assert
        assert code == 0
        assert capsys.readouterr().out == "switched to 'x' (was no login)\n"

    def test_dry_run_reports_the_unmanaged_preservation_it_would_make(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — foreign live login; --dry-run must preview the preserve
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        slot = FakeActiveSlot(credentials=_creds_for("foreign"), config=_config_for("acc-foreign"))

        # act
        code = _run(
            ["switch", "x", "--dry-run"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot),
        )

        # assert — no real path exists yet, so the note names the stash dir
        assert code == 0
        assert capsys.readouterr().out == (
            "dry run: switched to 'x' (was an unmanaged login)\n"
            "dry run: the previous unmanaged login was preserved under unclaimed/\n"
        )

    def test_switch_help_documents_its_flags(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        with pytest.raises(SystemExit):
            _run(["switch", "--help"], _use_cases(tmp_path))
        text = capsys.readouterr().out

        # assert — usage line pins nargs="?", the choices literal, both
        # flags; the help-text pins end at a newline so an XX-mutated or
        # dropped string can't contain them
        assert (
            "usage: cam switch [-h] [--strategy {best,next-available}] [--dry-run]\n"
            "                  [--model MODEL]\n"
            "                  [name]\n" in text
        )
        assert "account name (omit to rotate)\n" in text
        assert "instead of naming one\n" in text
        assert "describe the switch without applying it\n" in text
        assert "persisted yet\n" in text

    def test_an_unknown_strategy_is_rejected(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act / assert — argparse's choices= gate exits 2 before the use case
        with pytest.raises(SystemExit) as exited:
            _run(["switch", "--strategy", "bogus"], _use_cases(tmp_path))
        assert exited.value.code == 2
        assert "invalid choice" in capsys.readouterr().err

    def test_a_wiped_live_credential_is_quarantined_not_preserved(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — x's live tokens were wiped in place by an invalid_grant;
        # nothing recoverable, so the lineage tombstones instead of parking
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        _park(store, reader, "y")
        wiped = {"claudeAiOauth": {"accessToken": "", "refreshToken": "", "expiresAt": 1}}
        slot = FakeActiveSlot(credentials=wiped, config=_config_for("acc-x"))

        # act
        code = _run(["switch", "y"], _use_cases(tmp_path, store=store, reader=reader, slot=slot))

        # assert
        assert code == 0
        assert capsys.readouterr().out == (
            "switched to 'y' (was 'x')\nquarantined the wiped credential of 'x'\n"
        )
        assert [entry.name for entry in store.quarantined()] == ["x"]
