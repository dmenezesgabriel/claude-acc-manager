"""Unit tests for accounts.application.use_cases.switch_account.

The switch is the move model's core transaction: the outgoing live
credential returns to its account dir (or the unclaimed stash when it
matches no account), the target's stored credential moves into the live
slot composed with the machine's shared fields, the live config's
``oauthAccount`` is spliced, the named copy is deleted, and the active
pointer follows. Every step is covered by rollback.
"""

from pathlib import Path

import pytest
from support.failable_account_dir import FailableAccountDir
from support.failable_account_store import FailableAccountStore
from support.failable_active_slot import FailableActiveSlot
from support.fake_claude_locks import FakeClaudeLocks
from support.fake_clock import FakeClock
from support.fake_unclaimed_store import FakeUnclaimedStore

from claude_acc_manager.accounts.application.use_cases.switch_account import (
    SwitchAccount,
)
from claude_acc_manager.accounts.domain.credential_fields import refresh_token_fingerprint
from claude_acc_manager.accounts.domain.entities import Account, QuarantineEntry
from claude_acc_manager.accounts.domain.value_objects import AccountName


def _creds(name: str, **extra: object) -> dict[str, object]:
    oauth = {"accessToken": f"at-{name}", "refreshToken": f"rt-{name}"}
    return {"claudeAiOauth": oauth, **extra}


def _config(name: str) -> dict[str, object]:
    return {
        "oauthAccount": {
            "emailAddress": f"{name}@example.com",
            "accountUuid": f"acc-{name}",
        },
        "globalFlag": True,
    }


def _wiped() -> dict[str, object]:
    return {
        "claudeAiOauth": {
            "accessToken": "",
            "refreshToken": "",
            "expiresAt": 1,
            "scopes": ["user:profile"],
        }
    }


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


class _Wiring:
    """The collaborators one switch needs, wired to in-memory fakes."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        live_creds,
        live_config,
        scoped_into: str | None = None,
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
        self.locks = FakeClaudeLocks()
        self.switch = SwitchAccount(
            self.store,
            self.slot,
            self.files,
            self.unclaimed,
            self.locks,
            FakeClock(),
        )

    def park(self, name: str) -> None:
        """Register *name* with its credential parked in its account dir."""
        self.store.upsert(_account(name))
        self.files.put(
            self.store.account_dir(AccountName(name)),
            credentials=_creds(name),
            config=_config(name),
        )

    def go_live(self, name: str) -> None:
        """Register *name* and set it active — its dir holds config only."""
        self.park(name)
        self.files.delete_credentials(self.store.account_dir(AccountName(name)))
        self.store.set_active(AccountName(name))


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


class TestStrategies:
    """No explicit target → selection picks: rotation, next-available, best."""

    def test_bare_switch_rotates_past_the_live_account(self, tmp_path: Path):
        # arrange — x live; y, z parked
        wiring = _Wiring(tmp_path, live_creds=_creds("x"), live_config=_config("x"))
        wiring.go_live("x")
        wiring.park("y")
        wiring.park("z")

        # act
        result = wiring.switch.execute()

        # assert
        assert result.outcome == "switched"
        assert result.target == "y"
        assert result.previous == "x"
        assert result.unmanaged_live is False
        assert result.skipped == ()
        assert result.dry_run is False

    def test_rotation_skips_disabled_quarantined_and_credentialless(self, tmp_path: Path):
        # arrange — b disabled, c quarantined, d has no parked credential
        wiring = _Wiring(tmp_path, live_creds=_creds("a"), live_config=_config("a"))
        wiring.go_live("a")
        for name in ("b", "c", "d", "e"):
            wiring.park(name)
        wiring.store.set_enabled(AccountName("b"), False)
        wiring.files.delete_credentials(wiring.store.account_dir(AccountName("d")))

        # act — c carries a tombstone from an earlier invalid_grant
        wiring.store.set_quarantined(QuarantineEntry("c", "permanent_auth_error", "t", None))
        result = wiring.switch.execute()

        # assert — e wins; every skipped candidate is named
        assert result.target == "e"
        assert [(s.name, s.reason) for s in result.skipped] == [
            ("b", "disabled"),
            ("c", "quarantined"),
            ("d", "no-credentials"),
        ]

    def test_single_registered_account_reports_no_valid_target(self, tmp_path: Path):
        # arrange
        wiring = _Wiring(tmp_path, live_creds=_creds("a"), live_config=_config("a"))
        wiring.go_live("a")

        # act
        result = wiring.switch.execute()

        # assert
        assert result.outcome == "no-valid-target"
        assert result.target is None

    def test_next_available_skips_a_known_exhausted_account(self, tmp_path: Path):
        # arrange
        wiring = _Wiring(tmp_path, live_creds=_creds("a"), live_config=_config("a"))
        wiring.go_live("a")
        wiring.park("b")
        wiring.park("c")

        # act — b at its limit; c is unknown
        result = wiring.switch.execute(strategy="next-available", headroom={"b": 0.0})

        # assert
        assert result.target == "c"

    def test_all_candidates_exhausted_stays(self, tmp_path: Path):
        # arrange
        wiring = _Wiring(tmp_path, live_creds=_creds("a"), live_config=_config("a"))
        wiring.go_live("a")
        wiring.park("b")

        # act
        result = wiring.switch.execute(strategy="next-available", headroom={"b": 0.0})

        # assert
        assert result.outcome == "candidates-exhausted"
        assert result.previous == "a"
        assert result.unmanaged_live is False
        assert result.dry_run is False
        assert [(s.name, s.reason) for s in result.skipped] == [("b", "at-limit")]
        active = wiring.store.active()
        assert active is not None and active.name.value == "a"

    def test_stay_dry_run_keeps_the_dry_run_flag(self, tmp_path: Path):
        # arrange — exhaustion under --dry-run reports without touching locks
        wiring = _Wiring(tmp_path, live_creds=_creds("a"), live_config=_config("a"))
        wiring.go_live("a")
        wiring.park("b")

        # act
        result = wiring.switch.execute(strategy="next-available", headroom={"b": 0.0}, dry_run=True)

        # assert
        assert result.outcome == "candidates-exhausted"
        assert result.dry_run is True
        assert result.previous == "a"
        assert [(s.name, s.reason) for s in result.skipped] == [("b", "at-limit")]
        assert wiring.locks.acquired == []

    def test_best_switches_to_strictly_better(self, tmp_path: Path):
        # arrange
        wiring = _Wiring(tmp_path, live_creds=_creds("a"), live_config=_config("a"))
        wiring.go_live("a")
        wiring.park("b")
        wiring.park("c")

        # act
        result = wiring.switch.execute(strategy="best", headroom={"a": 20.0, "b": 30.0, "c": 90.0})

        # assert
        assert result.outcome == "switched"
        assert result.target == "c"

    def test_best_without_current_measurement_stays(self, tmp_path: Path):
        # arrange — nobody measured "a"
        wiring = _Wiring(tmp_path, live_creds=_creds("a"), live_config=_config("a"))
        wiring.go_live("a")
        wiring.park("b")

        # act
        result = wiring.switch.execute(strategy="best", headroom={"b": 90.0})

        # assert
        assert result.outcome == "usage-unavailable"
        assert wiring.slot.calls == []

    def test_anchor_falls_back_to_the_recorded_pointer(self, tmp_path: Path):
        # arrange — live is unmanaged; the recorded pointer anchors rotation
        wiring = _Wiring(tmp_path, live_creds=_creds("foreign"), live_config=_config("foreign"))
        wiring.go_live("a")  # recorded active, though the slot shows foreign
        wiring.park("b")

        # act
        result = wiring.switch.execute()

        # assert — rotation continues after the RECORDED anchor, and the
        # foreign login is preserved on the way out
        assert result.target == "b"
        assert len(wiring.unclaimed.preserved) == 1

    def test_recorded_anchor_picks_the_next_index_not_the_first(self, tmp_path: Path):
        # arrange — three parked accounts; the pointer sits on b, the slot
        # is foreign: rotation must land on c, not wrap to a
        wiring = _Wiring(tmp_path, live_creds=_creds("foreign"), live_config=_config("foreign"))
        for name in ("a", "b", "c"):
            wiring.park(name)
        wiring.store.set_active(AccountName("b"))

        # act
        result = wiring.switch.execute()

        # assert
        assert result.target == "c"

    def test_explicit_target_and_strategy_conflict(self, tmp_path: Path):
        # arrange
        wiring = _Wiring(tmp_path, live_creds=None, live_config=None)
        wiring.park("y")

        # act / assert
        with pytest.raises(ValueError, match="strategy"):
            wiring.switch.execute(AccountName("y"), strategy="best")

    def test_strategy_dry_run_picks_without_mutating(self, tmp_path: Path):
        # arrange — b is at its limit, so the dry-run result carries a skip note
        wiring = _Wiring(tmp_path, live_creds=_creds("a"), live_config=_config("a"))
        wiring.go_live("a")
        wiring.park("b")
        wiring.park("c")

        # act
        result = wiring.switch.execute(strategy="next-available", headroom={"b": 0.0}, dry_run=True)

        # assert
        assert result.outcome == "switched"
        assert result.dry_run is True
        assert result.target == "c"
        assert result.previous == "a"
        assert result.unmanaged_live is False
        assert [(s.name, s.reason) for s in result.skipped] == [("b", "at-limit")]
        assert wiring.slot.calls == []
        assert wiring.locks.acquired == []

    def test_strategy_dry_run_reports_the_unmanaged_live(self, tmp_path: Path):
        # arrange — the live login belongs to no account
        wiring = _Wiring(tmp_path, live_creds=_creds("foreign"), live_config=_config("foreign"))
        wiring.park("a")
        wiring.park("b")
        wiring.store.set_enabled(AccountName("a"), False)

        # act
        result = wiring.switch.execute(dry_run=True)

        # assert — rotation skips disabled a; the caller must see the stash warning
        assert result.outcome == "switched"
        assert result.target == "b"
        assert result.dry_run is True
        assert result.unmanaged_live is True
        assert result.previous is None
        assert wiring.locks.acquired == []


class TestDryRun:
    def test_dry_run_reports_without_mutating(self, tmp_path: Path):
        # arrange
        wiring = _Wiring(tmp_path, live_creds=_creds("x"), live_config=_config("x"))
        wiring.go_live("x")
        wiring.park("y")

        # act
        result = wiring.switch.execute(AccountName("y"), dry_run=True)

        # assert — the plan is reported; nothing moved
        assert result.outcome == "switched"
        assert result.dry_run is True
        assert result.target == "y"
        assert result.previous == "x"
        assert wiring.slot.read_credentials() == _creds("x")
        assert wiring.slot.calls == []
        assert wiring.files.read_credentials(wiring.store.account_dir(AccountName("y"))) == _creds(
            "y"
        )
        assert wiring.store.active() is not None
        assert wiring.store.active().name.value == "x"  # type: ignore[union-attr]
        assert wiring.locks.acquired == []

    def test_dry_run_reports_already_active(self, tmp_path: Path):
        # arrange — the target is the live account
        wiring = _Wiring(tmp_path, live_creds=_creds("x"), live_config=_config("x"))
        wiring.go_live("x")

        # act
        result = wiring.switch.execute(AccountName("x"), dry_run=True)

        # assert
        assert result.outcome == "already-active"
        assert result.target == "x"
        assert result.previous == "x"
        assert result.dry_run is True
        assert wiring.locks.acquired == []

    def test_dry_run_names_the_unmanaged_stash(self, tmp_path: Path):
        # arrange
        wiring = _Wiring(tmp_path, live_creds=_creds("foreign"), live_config=_config("foreign"))
        wiring.park("y")

        # act
        result = wiring.switch.execute(AccountName("y"), dry_run=True)

        # assert — caller can warn "the live login is unmanaged"
        assert result.outcome == "switched"
        assert result.unmanaged_live is True
        assert wiring.unclaimed.preserved == []


class TestRollback:
    """Every mutation step's failure restores the exact prior state."""

    def _wiring(self, tmp_path: Path) -> _Wiring:
        wiring = _Wiring(tmp_path, live_creds=_creds("x"), live_config=_config("x"))
        wiring.go_live("x")
        wiring.park("y")
        return wiring

    def _assert_restored(self, wiring: _Wiring) -> None:
        """The pre-switch state, byte for byte."""
        assert wiring.slot.read_credentials() == _creds("x")
        assert wiring.slot.read_config() == _config("x")
        x_dir = wiring.store.account_dir(AccountName("x"))
        y_dir = wiring.store.account_dir(AccountName("y"))
        assert wiring.files.read_credentials(x_dir) is None
        assert wiring.files.read_credentials(y_dir) == _creds("y")
        active = wiring.store.active()
        assert active is not None and active.name.value == "x"

    def test_failure_staging_live_credentials_restores_the_move_back(self, tmp_path: Path):
        # arrange — x's creds move back, then the live write dies
        wiring = self._wiring(tmp_path)
        wiring.slot.arm("write_credentials", OSError("disk full"))

        # act / assert
        with pytest.raises(OSError, match="disk full"):
            wiring.switch.execute(AccountName("y"))
        self._assert_restored(wiring)

    def test_failure_splicing_the_config_restores_credentials(self, tmp_path: Path):
        # arrange — the live creds were already replaced; splice dies
        wiring = self._wiring(tmp_path)
        wiring.slot.arm("splice_config_oauth_account", OSError("readonly"))

        # act / assert
        with pytest.raises(OSError, match="readonly"):
            wiring.switch.execute(AccountName("y"))
        self._assert_restored(wiring)

    def test_failure_deleting_the_named_copy_restores_the_slot(self, tmp_path: Path):
        # arrange
        wiring = self._wiring(tmp_path)
        wiring.files.arm("delete_credentials", OSError("fs busy"))

        # act / assert
        with pytest.raises(OSError, match="fs busy"):
            wiring.switch.execute(AccountName("y"))
        self._assert_restored(wiring)

    def test_failure_setting_the_active_pointer_restores_everything(self, tmp_path: Path):
        # arrange — the last step dies; all four prior effects unwind
        wiring = self._wiring(tmp_path)
        wiring.store.arm("set_active", OSError("registry locked"))

        # act / assert
        with pytest.raises(OSError, match="registry locked"):
            wiring.switch.execute(AccountName("y"))
        self._assert_restored(wiring)

    def test_preserve_failure_leaves_the_live_slot_alone(self, tmp_path: Path):
        # arrange — stashing the foreign login dies before any slot write
        wiring = _Wiring(tmp_path, live_creds=_creds("foreign"), live_config=_config("foreign"))
        wiring.park("y")
        wiring.unclaimed.error = OSError("no space")

        # act / assert
        with pytest.raises(OSError, match="no space"):
            wiring.switch.execute(AccountName("y"))
        assert wiring.slot.read_credentials() == _creds("foreign")

    def test_rollback_restores_an_absent_live_slot(self, tmp_path: Path):
        # arrange — no live creds at all; staging the target dies
        wiring = _Wiring(tmp_path, live_creds=None, live_config=None)
        wiring.park("y")
        wiring.slot.arm("splice_config_oauth_account", OSError("gone"))

        # act / assert
        with pytest.raises(OSError, match="gone"):
            wiring.switch.execute(AccountName("y"))
        assert wiring.slot.read_credentials() is None
        assert wiring.slot.read_config() is None
        y_dir = wiring.store.account_dir(AccountName("y"))
        assert wiring.files.read_credentials(y_dir) == _creds("y")


class TestRollbackNotes:
    """A restore that itself fails rides the original exception as a note."""

    def _notes(self, raised: pytest.ExceptionInfo[BaseException]) -> list[str]:
        return [str(note) for note in getattr(raised.value, "__notes__", [])]

    def test_pinned_live_credentials_restore_leaves_a_note(self, tmp_path: Path):
        # arrange — the staging write fails AND so does its own restore
        wiring = _Wiring(tmp_path, live_creds=_creds("x"), live_config=_config("x"))
        wiring.go_live("x")
        wiring.park("y")
        wiring.slot.pin("write_credentials", OSError("readonly"))

        # act / assert
        with pytest.raises(OSError, match="readonly") as raised:
            wiring.switch.execute(AccountName("y"))
        assert any("rollback of live credentials failed:" in note for note in self._notes(raised))

    def test_pinned_target_restore_leaves_a_note(self, tmp_path: Path):
        # arrange — no move-back (no live creds); set_active dies once, and
        # the pinned write_credentials fails when restoring the target copy
        wiring = _Wiring(tmp_path, live_creds=None, live_config=None)
        wiring.park("y")
        wiring.store.arm("set_active", OSError("locked"))
        wiring.files.pin("write_credentials", OSError("io"))

        # act / assert
        with pytest.raises(OSError, match="locked") as raised:
            wiring.switch.execute(AccountName("y"))
        assert any("rollback of target credential failed:" in note for note in self._notes(raised))

    def test_pinned_config_restore_leaves_a_note(self, tmp_path: Path):
        # arrange
        wiring = _Wiring(tmp_path, live_creds=_creds("x"), live_config=_config("x"))
        wiring.go_live("x")
        wiring.park("y")
        wiring.store.arm("set_active", OSError("locked"))
        wiring.slot.pin("write_config", OSError("fs gone"))

        # act / assert
        with pytest.raises(OSError, match="locked") as raised:
            wiring.switch.execute(AccountName("y"))
        assert any("rollback of live config failed:" in note for note in self._notes(raised))

    def test_pinned_active_pointer_restore_leaves_a_note(self, tmp_path: Path):
        # arrange — set_active fails as the mutation AND as its own restore
        wiring = _Wiring(tmp_path, live_creds=_creds("x"), live_config=_config("x"))
        wiring.go_live("x")
        wiring.park("y")
        wiring.store.pin("set_active", OSError("registry"))

        # act / assert
        with pytest.raises(OSError, match="registry") as raised:
            wiring.switch.execute(AccountName("y"))
        assert any("rollback of active pointer failed:" in note for note in self._notes(raised))

    def test_pinned_outgoing_restore_leaves_a_note(self, tmp_path: Path):
        # arrange — target-delete fails; its rollback's moved-back delete
        # hits the same pin
        wiring = _Wiring(tmp_path, live_creds=_creds("x"), live_config=_config("x"))
        wiring.go_live("x")
        wiring.park("y")
        wiring.files.pin("delete_credentials", OSError("fs busy"))

        # act / assert
        with pytest.raises(OSError, match="fs busy") as raised:
            wiring.switch.execute(AccountName("y"))
        assert any(
            "rollback of outgoing credential failed:" in note for note in self._notes(raised)
        )


class TestScopedShell:
    """A CLAUDE_CONFIG_DIR-scoped shell makes "the live slot" a parked dir."""

    def test_explicit_target_is_refused(self, tmp_path: Path):
        # arrange — the resolved live credentials path is x's parked file:
        # `cam` was launched inside a CLAUDE_CONFIG_DIR=accounts/x shell
        wiring = _Wiring(
            tmp_path, live_creds=_creds("x"), live_config=_config("x"), scoped_into="x"
        )
        wiring.go_live("x")
        wiring.park("y")

        # act / assert — no mutation may run against the scoped path
        scoped_dir = wiring.store.account_dir(AccountName("x"))
        with pytest.raises(ValueError, match=f"{scoped_dir}.*scoped shell"):
            wiring.switch.execute(AccountName("y"))
        assert wiring.files.read_credentials(wiring.store.account_dir(AccountName("y"))) == _creds(
            "y"
        )

    def test_strategy_path_is_refused(self, tmp_path: Path):
        # arrange
        wiring = _Wiring(
            tmp_path, live_creds=_creds("x"), live_config=_config("x"), scoped_into="x"
        )
        wiring.go_live("x")
        wiring.park("y")

        # act / assert
        with pytest.raises(ValueError, match="scoped shell"):
            wiring.switch.execute()

    def test_dry_run_is_refused(self, tmp_path: Path):
        # arrange — even a preview would describe the wrong "live" slot
        wiring = _Wiring(
            tmp_path, live_creds=_creds("x"), live_config=_config("x"), scoped_into="x"
        )
        wiring.go_live("x")
        wiring.park("y")

        # act / assert
        with pytest.raises(ValueError, match="scoped shell"):
            wiring.switch.execute(AccountName("y"), dry_run=True)
