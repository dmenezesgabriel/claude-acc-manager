"""``SwitchAccount`` safety — dry-run leaves no trace, rollback restores.

Every mutating step is covered by rollback: a failure mid-transaction must
return the live slot, the named dirs, and the active pointer to their
pre-switch state.
"""

from pathlib import Path

import pytest
from support.switch_rig import SwitchWiring as _Wiring
from support.switch_rig import switch_config as _config
from support.switch_rig import switch_creds as _creds

from claude_acc_manager.accounts.domain.value_objects import AccountName


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

    def test_rollback_restores_an_absent_active_pointer(self, tmp_path: Path):
        # arrange — no pointer was ever set; restoring it still calls
        # set_active(None), which is the only observable of that restore
        wiring = _Wiring(tmp_path, live_creds=None, live_config=None)
        wiring.park("y")
        wiring.slot.arm("splice_config_oauth_account", OSError("gone"))

        # act / assert
        with pytest.raises(OSError, match="gone"):
            wiring.switch.execute(AccountName("y"))
        assert wiring.store.calls == ["set_active"]


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
