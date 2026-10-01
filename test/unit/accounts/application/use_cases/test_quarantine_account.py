"""Unit tests for accounts.application.use_cases.quarantine_account."""

from pathlib import Path

import pytest
from support.fake_clock import FakeClock
from support.in_memory_account_store import InMemoryAccountStore

from claude_acc_manager.accounts.application.use_cases.quarantine_account import (
    QuarantineAccount,
)
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


class TestQuarantineAccount:
    """QuarantineAccount stamps a tombstone binding the dead lineage."""

    def test_records_the_entry_with_the_clock_time(self, tmp_path: Path):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))

        # act
        entry = QuarantineAccount(store, FakeClock()).execute(
            AccountName("work"), "permanent_auth_error", "sha256:abc"
        )

        # assert
        assert entry.name == "work"
        assert entry.reason == "permanent_auth_error"
        assert entry.at == "2026-09-10T12:00:00Z"
        assert entry.refresh_token_fingerprint == "sha256:abc"
        assert store.quarantined() == [entry]

    def test_unknown_account_raises_key_error(self, tmp_path: Path):
        # arrange
        store = InMemoryAccountStore(tmp_path)

        # act / assert
        with pytest.raises(KeyError, match="ghost"):
            QuarantineAccount(store, FakeClock()).execute(
                AccountName("ghost"), "permanent_auth_error", None
            )

    def test_a_fresh_fingerprint_replaces_the_old_tombstone(self, tmp_path: Path):
        # arrange — the lineage already died once at t0; a second failure
        # carries the NEW lineage's fingerprint
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        quarantine = QuarantineAccount(store, FakeClock("2026-09-10T00:00:00Z"))
        quarantine.execute(AccountName("work"), "permanent_auth_error", "sha256:old")

        # act — a later clock writes the newer tombstone
        later = QuarantineAccount(store, FakeClock("2026-09-11T00:00:00Z"))
        entry = later.execute(AccountName("work"), "permanent_auth_error", "sha256:new")

        # assert — one tombstone, carrying the lineage that actually failed
        assert store.quarantined() == [entry]
        assert entry.at == "2026-09-11T00:00:00Z"
        assert entry.refresh_token_fingerprint == "sha256:new"
