"""Unit tests for accounts.infrastructure.account_credential_store."""

import json
from pathlib import Path

import pytest
from support.in_memory_account_store import InMemoryAccountStore

from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.accounts.infrastructure.account_credential_store import (
    AccountCredentialStore,
)
from claude_acc_manager.usage.application.ports import CredentialStorePort
from claude_acc_manager.usage.domain.oauth_credential import StoredOAuthCredential


def make_credential_store(tmp_path: Path) -> tuple[AccountCredentialStore, InMemoryAccountStore]:
    store = InMemoryAccountStore(store_root=tmp_path / "store")
    return AccountCredentialStore(store), store


def write_credentials(account_dir: Path, document: dict[str, object]) -> None:
    account_dir.mkdir(parents=True, exist_ok=True)
    (account_dir / ".credentials.json").write_text(json.dumps(document), encoding="utf-8")


def read_credentials(account_dir: Path) -> dict[str, object]:
    text = (account_dir / ".credentials.json").read_text(encoding="utf-8")
    return json.loads(text)  # type: ignore[no-any-return]


class TestAdaptsThePort:
    def test_is_a_credential_store_port(self, tmp_path: Path):
        credentials, _ = make_credential_store(tmp_path)
        assert isinstance(credentials, CredentialStorePort)


class TestRead:
    def test_no_file_is_no_credential(self, tmp_path: Path):
        credentials, _ = make_credential_store(tmp_path)
        assert credentials.read("work") is None

    def test_parses_the_claude_ai_oauth_block(self, tmp_path: Path):
        # arrange
        credentials, store = make_credential_store(tmp_path)
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
        credentials, store = make_credential_store(tmp_path)
        account_dir = store.account_dir(AccountName("work"))
        write_credentials(account_dir, {})
        assert credentials.read("work") is None

    def test_non_object_claude_ai_oauth_is_no_credential(self, tmp_path: Path):
        credentials, store = make_credential_store(tmp_path)
        account_dir = store.account_dir(AccountName("work"))
        write_credentials(account_dir, {"claudeAiOauth": "not-an-object"})
        assert credentials.read("work") is None

    def test_a_torn_file_names_itself_credentials_in_the_error(self, tmp_path: Path):
        credentials, store = make_credential_store(tmp_path)
        account_dir = store.account_dir(AccountName("work"))
        account_dir.mkdir(parents=True)
        (account_dir / ".credentials.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError, match="credentials file"):
            credentials.read("work")


class TestPersistRotation:
    def test_writes_a_fresh_file_when_none_exists(self, tmp_path: Path):
        # arrange
        credentials, _ = make_credential_store(tmp_path)

        # act
        credentials.persist_rotation("work", "at-2", "rt-2", 456.0)

        # assert
        assert credentials.read("work") == StoredOAuthCredential(
            access_token="at-2", refresh_token="rt-2", expires_at_ms=456.0
        )

    def test_preserves_other_claude_ai_oauth_fields(self, tmp_path: Path):
        # arrange
        credentials, store = make_credential_store(tmp_path)
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
        credentials, store = make_credential_store(tmp_path)
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
        credentials, store = make_credential_store(tmp_path)
        account_dir = store.account_dir(AccountName("work"))
        credentials.persist_rotation("work", "at-2", "rt-2", 456.0)
        assert (account_dir / ".credentials.json").stat().st_mode & 0o777 == 0o600

    def test_a_torn_existing_file_names_itself_credentials_in_the_error(self, tmp_path: Path):
        credentials, store = make_credential_store(tmp_path)
        account_dir = store.account_dir(AccountName("work"))
        account_dir.mkdir(parents=True)
        (account_dir / ".credentials.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError, match="credentials file"):
            credentials.persist_rotation("work", "at-2", "rt-2", 456.0)
