"""Shared builders for the switch-account use-case tests.

The wiring fake composes every collaborator ``SwitchAccount`` needs behind
in-memory fakes; ``park``/``go_live`` set the two account states the
transaction moves between.
"""

from pathlib import Path

from claude_acc_manager.accounts.application.use_cases.switch_account import (
    SwitchAccount,
)
from claude_acc_manager.accounts.domain.entities import Account
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.shared.claude_contract import contract_for_version
from support.failable_account_dir import FailableAccountDir
from support.failable_account_store import FailableAccountStore
from support.failable_active_slot import FailableActiveSlot
from support.fake_claude_contract import FakeClaudeContractProbe
from support.fake_claude_locks import FakeClaudeLocks
from support.fake_clock import FakeClock
from support.fake_ops_lock import FakeOpsLock
from support.fake_unclaimed_store import FakeUnclaimedStore


def switch_creds(name: str, **extra: object) -> dict[str, object]:
    """A credential blob shaped like claude's ``.credentials.json``."""
    oauth = {"accessToken": f"at-{name}", "refreshToken": f"rt-{name}"}
    return {"claudeAiOauth": oauth, **extra}


def switch_config(name: str) -> dict[str, object]:
    """A live-config blob carrying the account's identity splice."""
    return {
        "oauthAccount": {
            "emailAddress": f"{name}@example.com",
            "accountUuid": f"acc-{name}",
        },
        "globalFlag": True,
    }


def wiped_creds() -> dict[str, object]:
    """The tombstone a wiped credential leaves behind."""
    return {
        "claudeAiOauth": {
            "accessToken": "",
            "refreshToken": "",
            "expiresAt": 1,
            "scopes": ["user:profile"],
        }
    }


def switch_account_entity(name: str) -> Account:
    """A stored account row for *name*."""
    return Account(
        name=AccountName(name),
        email=f"{name}@example.com",
        account_uuid=f"acc-{name}",
        organization_uuid=None,
        organization_name=None,
        added_at="2026-09-10T12:00:00Z",
        enabled=True,
    )


class SwitchWiring:
    """The collaborators one switch needs, wired to in-memory fakes."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        live_creds: dict[str, object],
        live_config: dict[str, object],
        scoped_into: str | None = None,
        shared_acquired: list[str] | None = None,
        claude_contract: FakeClaudeContractProbe | None = None,
    ) -> None:
        self.store = FailableAccountStore(tmp_path / "store")
        self.files = FailableAccountDir()
        live_path = None
        if scoped_into is not None:
            live_path = self.store.account_dir(AccountName(scoped_into)) / ".credentials.json"
        self.slot = FailableActiveSlot(
            credentials=live_creds, config=live_config, live_credentials_path=live_path
        )
        self.unclaimed = FakeUnclaimedStore()
        self.locks = FakeClaudeLocks(acquired=shared_acquired)
        self.ops = FakeOpsLock(acquired=shared_acquired)
        self.contract_probe = claude_contract or FakeClaudeContractProbe(
            contract_for_version((2, 1, 288))
        )
        self.switch = SwitchAccount(
            self.store,
            self.slot,
            self.files,
            self.unclaimed,
            self.locks,
            FakeClock(),
            self.ops,
            self.contract_probe,
        )

    def park(self, name: str) -> None:
        """Register *name* with its credential parked in its account dir."""
        self.store.upsert(switch_account_entity(name))
        self.files.put(
            self.store.account_dir(AccountName(name)),
            credentials=switch_creds(name),
            config=switch_config(name),
        )

    def go_live(self, name: str) -> None:
        """Register *name* and set it active — its dir holds config only."""
        self.park(name)
        self.files.delete_credentials(self.store.account_dir(AccountName(name)))
        self.store.set_active(AccountName(name))
