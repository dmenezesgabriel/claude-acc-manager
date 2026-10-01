"""Unit tests for accounts.application.use_cases.quarantine_dead_lineage."""

from pathlib import Path

import pytest
from support.fake_account_dir import FakeAccountDir
from support.fake_clock import FakeClock
from support.in_memory_account_store import InMemoryAccountStore

from claude_acc_manager.accounts.application.use_cases.quarantine_dead_lineage import (
    QuarantineDeadLineage,
)
from claude_acc_manager.accounts.domain.credential_fields import refresh_token_fingerprint
from claude_acc_manager.accounts.domain.entities import Account
from claude_acc_manager.accounts.domain.value_objects import AccountName


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


def _credentials(refresh_token: str) -> dict[str, object]:
    return {"claudeAiOauth": {"refreshToken": refresh_token}}


class TestQuarantineDeadLineage:
    """The use case reads the parked credential itself — the caller (a fetch
    that hit invalid_grant) knows the lineage died, not which file holds it."""

    def test_binds_the_parked_credentials_fingerprint(self, tmp_path: Path):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        files = FakeAccountDir()
        files.put(
            store.account_dir(AccountName("work")),
            credentials=_credentials("rt-dead"),
        )

        # act
        entry = QuarantineDeadLineage(store, files, FakeClock()).execute(AccountName("work"))

        # assert
        assert entry.name == "work"
        assert entry.reason == "permanent_auth_error"
        assert entry.at == "2026-09-10T12:00:00Z"
        assert entry.refresh_token_fingerprint == refresh_token_fingerprint(_credentials("rt-dead"))
        assert store.quarantined() == [entry]

    def test_no_parked_credential_binds_no_fingerprint(self, tmp_path: Path):
        # arrange — the account was live when its lineage died; nothing parked
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))

        # act
        entry = QuarantineDeadLineage(store, FakeAccountDir(), FakeClock()).execute(
            AccountName("work")
        )

        # assert
        assert entry.refresh_token_fingerprint is None
        assert store.quarantined() == [entry]

    def test_unknown_account_raises_key_error(self, tmp_path: Path):
        # arrange / act / assert
        with pytest.raises(KeyError, match="ghost"):
            QuarantineDeadLineage(
                InMemoryAccountStore(tmp_path), FakeAccountDir(), FakeClock()
            ).execute(AccountName("ghost"))

    def test_a_new_rejection_replaces_the_old_tombstone(self, tmp_path: Path):
        # arrange — the lineage already died once; a second rejection binds
        # the lineage that's actually parked now
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        files = FakeAccountDir()
        account_dir = store.account_dir(AccountName("work"))
        quarantine = QuarantineDeadLineage(store, files, FakeClock("2026-09-10T00:00:00Z"))
        quarantine.execute(AccountName("work"))
        files.put(account_dir, credentials=_credentials("rt-new"))

        # act — a later clock writes the newer tombstone
        later = QuarantineDeadLineage(store, files, FakeClock("2026-09-11T00:00:00Z"))
        entry = later.execute(AccountName("work"))

        # assert — one tombstone, carrying the lineage that actually failed
        assert store.quarantined() == [entry]
        assert entry.at == "2026-09-11T00:00:00Z"
        assert entry.refresh_token_fingerprint == refresh_token_fingerprint(_credentials("rt-new"))
