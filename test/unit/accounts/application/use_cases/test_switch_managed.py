"""``SwitchAccount`` — managed-to-managed moves and outgoing credential classes.

The switch is the move model's core transaction: the outgoing live credential
returns to its account dir (or the unclaimed stash when it matches no
account), the target's stored credential moves into the live slot composed
with the machine's shared fields, and the active pointer follows.
"""

from pathlib import Path

import pytest
from support.fake_clock import FakeClock
from support.switch_rig import SwitchWiring as _Wiring
from support.switch_rig import switch_account_entity as _account
from support.switch_rig import switch_config as _config
from support.switch_rig import switch_creds as _creds
from support.switch_rig import wiped_creds as _wiped

import claude_acc_manager.accounts.infrastructure.ops_lock as ops_lock
from claude_acc_manager.accounts.application.use_cases.switch_account import (
    SwitchAccount,
)
from claude_acc_manager.accounts.domain.credential_fields import (
    refresh_token_fingerprint,
)
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.accounts.infrastructure.ops_lock import FlockOpsLock


class TestManagedToManaged:
    def test_the_five_steps_land(self, tmp_path: Path):
        # arrange — x live, y parked
        wiring = _Wiring(tmp_path, live_creds=_creds("x"), live_config=_config("x"))
        wiring.go_live("x")
        wiring.park("y")

        # act
        result = wiring.switch.execute(AccountName("y"))

        # assert — the transaction's five effects
        assert result.outcome == "switched"
        assert result.target == "y"
        assert result.previous == "x"
        assert result.unmanaged_live is False
        assert result.preserved_to is None
        assert result.quarantined == ()
        x_dir = wiring.store.account_dir(AccountName("x"))
        y_dir = wiring.store.account_dir(AccountName("y"))
        assert wiring.files.read_credentials(x_dir) == _creds("x")  # move-back
        assert wiring.slot.read_credentials() == _creds("y")  # staged
        assert wiring.files.read_credentials(y_dir) is None  # named copy gone
        active = wiring.store.active()
        assert active is not None and active.name.value == "y"  # pointer

    def test_shared_fields_come_from_the_live_blob(self, tmp_path: Path):
        # arrange — live carries the machine's mcpOAuth generation
        live = _creds("x", mcpOAuth={"server": "new-gen"})
        target = _creds("y", mcpOAuth={"server": "stale"})
        wiring = _Wiring(tmp_path, live_creds=live, live_config=_config("x"))
        wiring.go_live("x")
        wiring.park("y")
        y_dir = wiring.store.account_dir(AccountName("y"))
        wiring.files.write_credentials(y_dir, target)

        # act
        wiring.switch.execute(AccountName("y"))

        # assert — slot-owned keys from target, shared keys from live
        staged = wiring.slot.read_credentials()
        assert staged is not None
        assert staged["claudeAiOauth"] == _creds("y")["claudeAiOauth"]
        assert staged["mcpOAuth"] == {"server": "new-gen"}

    def test_oauth_account_is_spliced_into_the_live_config(self, tmp_path: Path):
        # arrange
        wiring = _Wiring(tmp_path, live_creds=_creds("x"), live_config=_config("x"))
        wiring.go_live("x")
        wiring.park("y")

        # act
        wiring.switch.execute(AccountName("y"))

        # assert — only oauthAccount changes; global prefs survive
        config = wiring.slot.read_config()
        assert config is not None
        oauth = config["oauthAccount"]
        assert oauth["accountUuid"] == "acc-y"  # type: ignore[index]
        assert config["globalFlag"] is True

    def test_mutations_run_under_both_claude_locks(self, tmp_path: Path):
        # arrange
        wiring = _Wiring(tmp_path, live_creds=_creds("x"), live_config=_config("x"))
        wiring.go_live("x")
        wiring.park("y")

        # act
        wiring.switch.execute(AccountName("y"))

        # assert — every mutation happened inside the held locks
        assert set(wiring.locks.acquired) == {"credentials", "config"}
        assert len(wiring.locks.acquired) == len(wiring.locks.released) == 2

    def test_the_ops_lock_wraps_the_claude_locks(self, tmp_path: Path):
        # arrange — one recorder sees cam's ops lock and claude's two in order
        order: list[str] = []
        wiring = _Wiring(
            tmp_path,
            live_creds=_creds("x"),
            live_config=_config("x"),
            shared_acquired=order,
        )
        wiring.go_live("x")
        wiring.park("y")

        # act
        wiring.switch.execute(AccountName("y"))

        # assert — cam serializes itself before it coordinates with claude
        assert order == ["ops", "credentials", "config"]

    def test_a_dry_run_takes_no_ops_lock(self, tmp_path: Path):
        # arrange
        wiring = _Wiring(tmp_path, live_creds=_creds("x"), live_config=_config("x"))
        wiring.go_live("x")
        wiring.park("y")

        # act
        wiring.switch.execute(AccountName("y"), dry_run=True)

        # assert — previews read; they never serialize against writers
        assert wiring.ops.acquired == []
        assert wiring.locks.acquired == []

    def test_a_held_ops_lock_refuses_the_switch(self, tmp_path: Path, monkeypatch):
        # arrange — the REAL store lock, held as a second cam process would;
        # the switch must refuse before touching claude's locks or a file
        monkeypatch.setattr(ops_lock, "DEFAULT_TIMEOUT_S", 0.0)
        wiring = _Wiring(tmp_path, live_creds=_creds("x"), live_config=_config("x"))
        wiring.go_live("x")
        wiring.park("y")
        real_ops = FlockOpsLock(tmp_path / "store")
        switch = SwitchAccount(
            wiring.store,
            wiring.slot,
            wiring.files,
            wiring.unclaimed,
            wiring.locks,
            FakeClock(),
            real_ops,
            wiring.contract_probe,
        )

        # act / assert
        with real_ops.ops_locked(), pytest.raises(TimeoutError):
            switch.execute(AccountName("y"))
        y_dir = wiring.store.account_dir(AccountName("y"))
        assert wiring.locks.acquired == []
        assert wiring.files.read_credentials(y_dir) is not None

    def test_switching_to_the_live_account_is_a_noop(self, tmp_path: Path):
        # arrange
        wiring = _Wiring(tmp_path, live_creds=_creds("x"), live_config=_config("x"))
        wiring.go_live("x")
        wiring.park("y")

        # act
        result = wiring.switch.execute(AccountName("x"))

        # assert
        assert result.outcome == "already-active"
        assert result.target == "x"
        assert result.previous == "x"
        assert result.quarantined == ()
        assert wiring.slot.read_credentials() == _creds("x")
        assert wiring.slot.calls == []

    def test_wiped_active_target_tombstones_then_already_active(self, tmp_path: Path):
        # arrange — x is live with wiped tokens; the tombstone lands
        # before the already-active short-circuit
        wiring = _Wiring(tmp_path, live_creds=_wiped(), live_config=_config("x"))
        wiring.go_live("x")

        # act
        result = wiring.switch.execute(AccountName("x"))

        # assert
        assert result.outcome == "already-active"
        assert result.target == "x"
        assert result.quarantined == ("x",)
        (entry,) = wiring.store.quarantined()
        assert entry.reason == "permanent_auth_error"


class TestOutgoingClasses:
    def test_unmanaged_live_login_is_preserved(self, tmp_path: Path):
        # arrange — a login cam never registered sits in the live slot
        wiring = _Wiring(
            tmp_path,
            live_creds=_creds("foreign"),
            live_config=_config("foreign"),
        )
        wiring.park("y")

        # act
        result = wiring.switch.execute(AccountName("y"))

        # assert — nothing destroyed; the foreign pair lands in unclaimed/
        assert result.outcome == "switched"
        assert result.previous is None
        assert result.unmanaged_live is True
        assert result.preserved_to is not None
        assert wiring.unclaimed.preserved == [(_creds("foreign"), _config("foreign"), "foreign")]
        assert wiring.slot.read_credentials() == _creds("y")

    def test_no_live_credentials_just_activates_the_target(self, tmp_path: Path):
        # arrange — claude was never run on this machine
        wiring = _Wiring(tmp_path, live_creds=None, live_config=None)
        wiring.park("y")

        # act
        result = wiring.switch.execute(AccountName("y"))

        # assert
        assert result.outcome == "switched"
        assert result.previous is None
        assert result.unmanaged_live is False
        assert wiring.unclaimed.preserved == []
        assert wiring.slot.read_credentials() == _creds("y")

    def test_config_identity_without_credentials_does_not_quarantine(self, tmp_path: Path):
        # arrange — the live config still names x, but the credential file
        # is gone: there is no wiped blob to blame, nothing to tombstone
        wiring = _Wiring(tmp_path, live_creds=None, live_config=_config("x"))
        wiring.go_live("x")
        wiring.park("y")

        # act
        result = wiring.switch.execute(AccountName("y"))

        # assert
        assert result.outcome == "switched"
        assert wiring.store.quarantined() == []

    def test_a_config_only_match_reports_no_previous_account(self, tmp_path: Path):
        # arrange — the live config names x but no credential sits in the
        # slot: no managed login is actually live, so previous stays None
        wiring = _Wiring(tmp_path, live_creds=None, live_config=_config("x"))
        wiring.park("x")
        wiring.park("y")

        # act
        result = wiring.switch.execute(AccountName("y"), dry_run=True)

        # assert
        assert result.outcome == "switched"
        assert result.previous is None

    @pytest.mark.parametrize("dry_run", [False, True])
    def test_registered_target_without_a_config_file_raises(self, tmp_path: Path, dry_run: bool):
        # arrange — y has a credential but no config file at all
        wiring = _Wiring(tmp_path, live_creds=None, live_config=None)
        wiring.store.upsert(_account("y"))
        y_dir = wiring.store.account_dir(AccountName("y"))
        wiring.files.put(y_dir, credentials=_creds("y"))

        # act / assert
        with pytest.raises(ValueError, match="'y' config carries no oauthAccount"):
            wiring.switch.execute(AccountName("y"), dry_run=dry_run)

    def test_wiped_managed_credentials_quarantine_the_lineage(self, tmp_path: Path):
        # arrange — claude emptied x's tokens after invalid_grant; x's dir
        # holds no credential because x was live (the move model)
        wiring = _Wiring(tmp_path, live_creds=_wiped(), live_config=_config("x"))
        wiring.go_live("x")
        wiring.park("y")

        # act
        result = wiring.switch.execute(AccountName("y"))

        # assert — dead bytes destroyed, the lineage tombstoned, not parked
        assert result.outcome == "switched"
        x_dir = wiring.store.account_dir(AccountName("x"))
        assert wiring.files.read_credentials(x_dir) is None
        assert wiring.unclaimed.preserved == []
        (entry,) = wiring.store.quarantined()
        assert entry.name == "x"
        assert entry.reason == "permanent_auth_error"
        assert entry.at == "2026-09-10T12:00:00Z"
        assert entry.refresh_token_fingerprint == refresh_token_fingerprint(_wiped())
        assert result.quarantined == ("x",)

    def test_wiped_foreign_credentials_are_destroyed_not_kept(self, tmp_path: Path):
        # arrange — a wiped blob that matches no account is dead weight
        wiring = _Wiring(tmp_path, live_creds=_wiped(), live_config=_config("foreign"))
        wiring.park("y")

        # act
        result = wiring.switch.execute(AccountName("y"))

        # assert
        assert result.outcome == "switched"
        assert result.unmanaged_live is False
        assert wiring.unclaimed.preserved == []
        assert wiring.store.quarantined() == []

    def test_unknown_target_raises(self, tmp_path: Path):
        # arrange
        wiring = _Wiring(tmp_path, live_creds=None, live_config=None)

        # act / assert
        with pytest.raises(KeyError, match="ghost"):
            wiring.switch.execute(AccountName("ghost"))

    @pytest.mark.parametrize("dry_run", [False, True])
    def test_registered_target_without_credentials_raises(self, tmp_path: Path, dry_run: bool):
        # arrange — y is registered but its credential was never captured
        wiring = _Wiring(tmp_path, live_creds=None, live_config=None)
        wiring.store.upsert(_account("y"))
        wiring.files.put(wiring.store.account_dir(AccountName("y")), config=_config("y"))

        # act / assert — the check runs in both preview and transact paths
        with pytest.raises(ValueError, match="y.*no stored credentials|no stored credentials.*y"):
            wiring.switch.execute(AccountName("y"), dry_run=dry_run)

    @pytest.mark.parametrize("dry_run", [False, True])
    def test_registered_target_without_oauth_account_raises(self, tmp_path: Path, dry_run: bool):
        # arrange — y has a credential but its config lost the marker
        wiring = _Wiring(tmp_path, live_creds=None, live_config=None)
        wiring.store.upsert(_account("y"))
        y_dir = wiring.store.account_dir(AccountName("y"))
        wiring.files.put(y_dir, credentials=_creds("y"), config={"globalFlag": True})

        # act / assert
        with pytest.raises(ValueError, match="'y' config carries no oauthAccount"):
            wiring.switch.execute(AccountName("y"), dry_run=dry_run)
