"""``SwitchAccount`` strategies — the named/both-error/rotate move shapes."""

from pathlib import Path

import pytest
from support.switch_rig import SwitchWiring as _Wiring
from support.switch_rig import switch_config as _config
from support.switch_rig import switch_creds as _creds

from claude_acc_manager.accounts.domain.entities import QuarantineEntry
from claude_acc_manager.accounts.domain.value_objects import AccountName


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

    def test_a_config_only_match_does_not_steal_the_rotation_anchor(self, tmp_path: Path):
        # arrange — the live config names x but the credential is gone, and
        # the recorded pointer says y: y anchors the walk, not x's namesake
        wiring = _Wiring(tmp_path, live_creds=None, live_config=_config("x"))
        wiring.park("x")
        wiring.park("y")
        wiring.park("z")
        wiring.store.set_active(AccountName("y"))

        # act
        result = wiring.switch.execute(dry_run=True)

        # assert — rotation walks past y's index, landing on z (never on y)
        assert result.target == "z"

    def test_a_config_only_match_is_not_the_previous_on_a_pick(self, tmp_path: Path):
        # arrange — the strategy path also reports no previous when only the
        # config names x and no credential sits in the slot
        wiring = _Wiring(tmp_path, live_creds=None, live_config=_config("x"))
        wiring.park("x")
        wiring.park("y")

        # act
        result = wiring.switch.execute(strategy="next-available", dry_run=True)

        # assert
        assert result.previous is None

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
