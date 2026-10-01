"""Unit tests for accounts.application.use_cases.set_account_enabled."""

from pathlib import Path

import pytest
from support.in_memory_account_store import InMemoryAccountStore

from claude_acc_manager.accounts.application.use_cases.set_account_enabled import (
    SetAccountEnabled,
)
from claude_acc_manager.accounts.domain.entities import Account
from claude_acc_manager.accounts.domain.value_objects import AccountName


def _account(name: str, enabled: bool = True) -> Account:
    return Account(
        name=AccountName(name),
        email=f"{name}@example.com",
        account_uuid=f"acc-{name}",
        organization_uuid=None,
        organization_name=None,
        added_at="2026-09-10T12:00:00Z",
        enabled=enabled,
    )


class TestSetAccountEnabled:
    """SetAccountEnabled flips the enabled flag used to gate automatic picks."""

    def test_disables_an_enabled_account(self, tmp_path: Path):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))

        # act
        updated = SetAccountEnabled(store).execute(AccountName("work"), enabled=False)

        # assert
        persisted = store.get(AccountName("work"))
        assert updated.enabled is False
        assert persisted is not None and persisted.enabled is False

    def test_enables_a_disabled_account(self, tmp_path: Path):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work", enabled=False))

        # act
        updated = SetAccountEnabled(store).execute(AccountName("work"), enabled=True)

        # assert
        assert updated.enabled is True

    def test_unknown_account_raises_key_error(self, tmp_path: Path):
        # arrange
        store = InMemoryAccountStore(tmp_path)

        # act / assert
        with pytest.raises(KeyError, match="work"):
            SetAccountEnabled(store).execute(AccountName("work"), enabled=False)

    def test_setting_the_same_flag_is_a_noop(self, tmp_path: Path):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work", enabled=True))

        # act
        updated = SetAccountEnabled(store).execute(AccountName("work"), enabled=True)

        # assert
        assert updated.enabled is True
