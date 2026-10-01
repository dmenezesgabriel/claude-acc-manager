"""Unit tests for accounts.infrastructure.account_credential_store."""

import json
from pathlib import Path

import pytest
from support.fake_active_slot import FakeActiveSlot
from support.in_memory_account_store import InMemoryAccountStore

from claude_acc_manager.accounts.domain.entities import Account
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.accounts.infrastructure.account_credential_store import (
    AccountCredentialStore,
)
from claude_acc_manager.usage.application.ports import CredentialStorePort
from claude_acc_manager.usage.domain.oauth_credential import StoredOAuthCredential


def _account(name: str) -> Account:
    return Account(
        name=AccountName(name),
        email=f"{name}@example.com",
        account_uuid=f"acc-{name}",
        organization_uuid=None,
        organization_name=None,
        added_at="2026-09-10T12:00:00Z",
        enabled=True,
    )


def _config(name: str) -> dict[str, object]:
    return {"oauthAccount": {"emailAddress": f"{name}@x.io", "accountUuid": f"acc-{name}"}}


def make_credential_store(
    tmp_path: Path,
    *,
    live_credentials: dict[str, object] | None = None,
    live_config: dict[str, object] | None = None,
) -> tuple[AccountCredentialStore, InMemoryAccountStore, FakeActiveSlot]:
    store = InMemoryAccountStore(store_root=tmp_path / "store")
    slot = FakeActiveSlot(credentials=live_credentials, config=live_config)
    return AccountCredentialStore(store, slot), store, slot


def write_credentials(account_dir: Path, document: dict[str, object]) -> None:
    account_dir.mkdir(parents=True, exist_ok=True)
    (account_dir / ".credentials.json").write_text(json.dumps(document), encoding="utf-8")


def read_credentials(account_dir: Path) -> dict[str, object]:
    text = (account_dir / ".credentials.json").read_text(encoding="utf-8")
    return json.loads(text)  # type: ignore[no-any-return]


class TestAdaptsThePort:
    def test_is_a_credential_store_port(self, tmp_path: Path):
        credentials, _, _ = make_credential_store(tmp_path)
        assert isinstance(credentials, CredentialStorePort)


class TestRead:
    def test_no_file_is_no_credential(self, tmp_path: Path):
        credentials, _, _ = make_credential_store(tmp_path)
        assert credentials.read("work") is None

    def test_parses_the_claude_ai_oauth_block(self, tmp_path: Path):
        # arrange
        credentials, store, _ = make_credential_store(tmp_path)
        account_dir = store.account_dir(AccountName("work"))
        write_credentials(
            account_dir,
            {"claudeAiOauth": {"accessToken": "at-1", "refreshToken": "rt-1", "expiresAt": 123.0}},
        )

        # act / assert
        assert credentials.read("work") == StoredOAuthCredential(
            access_token="at-1", refresh_token="rt-1", expires_at_ms=123.0
        )

    def test_missing_claude_ai_oauth_key_is_no_credential(self, tmp_path: Path):
        credentials, store, _ = make_credential_store(tmp_path)
        account_dir = store.account_dir(AccountName("work"))
        write_credentials(account_dir, {})
        assert credentials.read("work") is None

    def test_non_object_claude_ai_oauth_is_no_credential(self, tmp_path: Path):
        credentials, store, _ = make_credential_store(tmp_path)
        account_dir = store.account_dir(AccountName("work"))
        write_credentials(account_dir, {"claudeAiOauth": "not-an-object"})
        assert credentials.read("work") is None

    def test_a_torn_file_names_itself_credentials_in_the_error(self, tmp_path: Path):
        credentials, store, _ = make_credential_store(tmp_path)
        account_dir = store.account_dir(AccountName("work"))
        account_dir.mkdir(parents=True)
        (account_dir / ".credentials.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError, match="credentials file"):
            credentials.read("work")

    def test_the_live_account_reads_the_live_slot(self, tmp_path: Path):
        # arrange — work is active: its dir is parked empty, its tokens are live
        live_creds = {"claudeAiOauth": {"accessToken": "at-live", "refreshToken": "rt-live"}}
        credentials, store, _ = make_credential_store(
            tmp_path, live_credentials=live_creds, live_config=_config("work")
        )
        store.upsert(_account("work"))

        # act / assert — the move model: only the live slot can answer
        assert credentials.read("work") == StoredOAuthCredential(
            access_token="at-live", refresh_token="rt-live", expires_at_ms=None
        )

    def test_unregistered_name_never_reads_the_live_slot(self, tmp_path: Path):
        # arrange — "ghost" has no registry entry, so no uuid to match
        live_creds = {"claudeAiOauth": {"accessToken": "at-live"}}
        credentials, _, _ = make_credential_store(
            tmp_path, live_credentials=live_creds, live_config=_config("work")
        )

        # act / assert — the live credential must not leak under a stray key
        assert credentials.read("ghost") is None
        credentials.persist_rotation("ghost", "at-2", "rt-2", 456.0)  # parked write is fine

    def test_a_parked_account_reads_its_own_file_not_the_live_slot(self, tmp_path: Path):
        # arrange — work is parked while "other" owns the live slot
        live_creds = {"claudeAiOauth": {"accessToken": "at-live"}}
        credentials, store, _ = make_credential_store(
            tmp_path, live_credentials=live_creds, live_config=_config("other")
        )
        store.upsert(_account("work"))
        write_credentials(
            store.account_dir(AccountName("work")),
            {"claudeAiOauth": {"accessToken": "at-parked", "refreshToken": "rt-parked"}},
        )

        # act / assert
        assert credentials.read("work") == StoredOAuthCredential(
            access_token="at-parked", refresh_token="rt-parked", expires_at_ms=None
        )

    def test_live_match_but_absent_slot_credentials_is_no_credential(self, tmp_path: Path):
        # arrange — config names work but the credential file is gone
        credentials, store, _ = make_credential_store(
            tmp_path, live_credentials=None, live_config=_config("work")
        )
        store.upsert(_account("work"))

        # act / assert
        assert credentials.read("work") is None

    def test_unattributable_live_slot_reads_the_parked_file(self, tmp_path: Path):
        # arrange — the live config has no oauthAccount: can't tell whose it is
        live_creds = {"claudeAiOauth": {"accessToken": "at-live"}}
        credentials, store, _ = make_credential_store(
            tmp_path, live_credentials=live_creds, live_config=None
        )
        store.upsert(_account("work"))
        write_credentials(
            store.account_dir(AccountName("work")),
            {"claudeAiOauth": {"accessToken": "at-parked"}},
        )

        # act / assert
        assert credentials.read("work") == StoredOAuthCredential(
            access_token="at-parked", refresh_token=None, expires_at_ms=None
        )


class TestPersistRotation:
    def test_writes_a_fresh_file_when_none_exists(self, tmp_path: Path):
        # arrange
        credentials, _, _ = make_credential_store(tmp_path)

        # act
        credentials.persist_rotation("work", "at-2", "rt-2", 456.0)

        # assert
        assert credentials.read("work") == StoredOAuthCredential(
            access_token="at-2", refresh_token="rt-2", expires_at_ms=456.0
        )

    def test_preserves_other_claude_ai_oauth_fields(self, tmp_path: Path):
        # arrange
        credentials, store, _ = make_credential_store(tmp_path)
        account_dir = store.account_dir(AccountName("work"))
        write_credentials(
            account_dir,
            {
                "claudeAiOauth": {
                    "accessToken": "at-1",
                    "refreshToken": "rt-1",
                    "expiresAt": 123.0,
                    "scopes": ["user:inference"],
                    "subscriptionType": "pro",
                }
            },
        )

        # act
        credentials.persist_rotation("work", "at-2", "rt-2", 456.0)

        # assert
        document = read_credentials(account_dir)
        oauth = document["claudeAiOauth"]
        assert isinstance(oauth, dict)
        assert oauth["scopes"] == ["user:inference"]
        assert oauth["subscriptionType"] == "pro"
        assert oauth["accessToken"] == "at-2"
        assert oauth["refreshToken"] == "rt-2"
        assert oauth["expiresAt"] == 456.0

    def test_preserves_a_sibling_top_level_key(self, tmp_path: Path):
        # arrange — e.g. organizationUuid, seen alongside claudeAiOauth on
        # long-lived credentials (docs/architecture.md §3)
        credentials, store, _ = make_credential_store(tmp_path)
        account_dir = store.account_dir(AccountName("work"))
        write_credentials(
            account_dir,
            {"claudeAiOauth": {"accessToken": "at-1"}, "organizationUuid": "org-1"},
        )

        # act
        credentials.persist_rotation("work", "at-2", "rt-2", 456.0)

        # assert
        assert read_credentials(account_dir)["organizationUuid"] == "org-1"

    def test_atomic_write_leaves_the_file_private(self, tmp_path: Path):
        credentials, store, _ = make_credential_store(tmp_path)
        account_dir = store.account_dir(AccountName("work"))
        credentials.persist_rotation("work", "at-2", "rt-2", 456.0)
        assert (account_dir / ".credentials.json").stat().st_mode & 0o777 == 0o600

    def test_a_torn_existing_file_names_itself_credentials_in_the_error(self, tmp_path: Path):
        credentials, store, _ = make_credential_store(tmp_path)
        account_dir = store.account_dir(AccountName("work"))
        account_dir.mkdir(parents=True)
        (account_dir / ".credentials.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError, match="credentials file"):
            credentials.persist_rotation("work", "at-2", "rt-2", 456.0)

    def test_persisting_the_live_account_refuses_to_fork_the_lineage(self, tmp_path: Path):
        # arrange — work's rotating lineage lives in the live slot; a parked
        # write would fork it (one lineage, one copy — ADR-0009)
        credentials, store, _ = make_credential_store(
            tmp_path,
            live_credentials={"claudeAiOauth": {"accessToken": "at-live"}},
            live_config=_config("work"),
        )
        store.upsert(_account("work"))

        # act / assert
        # the $ anchor kills XX-wrapping mutants of the second literal
        with pytest.raises(ValueError, match="'work' is live.*refusing to write a parked copy$"):
            credentials.persist_rotation("work", "at-2", "rt-2", 456.0)
