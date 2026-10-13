"""``SwitchAccount`` environment edges — scoped-shell live path, contract gate."""

from pathlib import Path

import pytest
from support.fake_claude_contract import FakeClaudeContractProbe
from support.switch_rig import SwitchWiring as _Wiring
from support.switch_rig import switch_config as _config
from support.switch_rig import switch_creds as _creds

from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.shared.claude_contract import (
    ClaudeContract,
    UnsupportedClaudeVersionError,
    contract_for_version,
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


class TestContractGate:
    """Mutating switches hold the claude-version contract; previews never probe.

    The gate sits at the top of the transaction — before the ops lock, so a
    doomed switch never serializes — while ``dry_run`` previews stay pure
    reads that work with no verifiable claude at all.
    """

    def _wiring(self, tmp_path: Path, contract: ClaudeContract) -> _Wiring:
        wiring = _Wiring(
            tmp_path,
            live_creds=_creds("x"),
            live_config=_config("x"),
            claude_contract=FakeClaudeContractProbe(contract),
        )
        wiring.go_live("x")
        wiring.park("y")
        return wiring

    def _assert_untouched(
        self,
        wiring: _Wiring,
        store_calls: list[str],
        file_calls: list[tuple[str, Path]],
    ) -> None:
        """No lock was taken, no write was attempted, and the state held."""
        assert wiring.ops.acquired == []
        assert wiring.locks.acquired == []
        assert wiring.slot.calls == []
        assert wiring.store.calls == store_calls
        assert wiring.files.calls == file_calls
        assert wiring.slot.read_credentials() == _creds("x")
        y_dir = wiring.store.account_dir(AccountName("y"))
        assert wiring.files.read_credentials(y_dir) == _creds("y")
        active = wiring.store.active()
        assert active is not None and active.name.value == "x"

    def test_below_band_refuses_before_any_lock(self, tmp_path: Path):
        # arrange — claude predates the contract's introduction
        wiring = self._wiring(tmp_path, contract_for_version((0, 2, 126)))
        store_calls, file_calls = list(wiring.store.calls), list(wiring.files.calls)

        # act / assert
        with pytest.raises(UnsupportedClaudeVersionError, match="0.2.126"):
            wiring.switch.execute(AccountName("y"))
        assert wiring.contract_probe.probes == 1
        self._assert_untouched(wiring, store_calls, file_calls)

    def test_above_band_refuses_naming_the_override(self, tmp_path: Path):
        # arrange — claude is newer than the verified band
        wiring = self._wiring(tmp_path, contract_for_version((2, 2, 0)))
        store_calls, file_calls = list(wiring.store.calls), list(wiring.files.calls)

        # act / assert
        with pytest.raises(UnsupportedClaudeVersionError, match="CAM_ASSUME_CLAUDE_CONTRACT"):
            wiring.switch.execute(AccountName("y"))
        self._assert_untouched(wiring, store_calls, file_calls)

    def test_undetermined_version_refuses(self, tmp_path: Path):
        # arrange — no claude answered the probe
        wiring = self._wiring(tmp_path, contract_for_version(None))
        store_calls, file_calls = list(wiring.store.calls), list(wiring.files.calls)

        # act / assert
        with pytest.raises(UnsupportedClaudeVersionError, match="could not determine"):
            wiring.switch.execute(AccountName("y"))
        self._assert_untouched(wiring, store_calls, file_calls)

    def test_probe_failure_refuses_with_the_failure_reason(self, tmp_path: Path):
        # arrange — the binary answered badly; the reason rides the refusal
        contract = ClaudeContract(
            version=None,
            supported=False,
            assumed=False,
            reason="claude --version exited 1: nope",
        )
        wiring = self._wiring(tmp_path, contract)
        store_calls, file_calls = list(wiring.store.calls), list(wiring.files.calls)

        # act / assert
        with pytest.raises(UnsupportedClaudeVersionError, match="exited 1"):
            wiring.switch.execute(AccountName("y"))
        self._assert_untouched(wiring, store_calls, file_calls)

    def test_the_strategy_path_is_gated(self, tmp_path: Path):
        # arrange — selection-driven switches mutate through the same gate
        wiring = self._wiring(tmp_path, contract_for_version((2, 1, 143)))

        # act / assert
        with pytest.raises(UnsupportedClaudeVersionError, match="2.1.143"):
            wiring.switch.execute()

    def test_an_assumed_contract_proceeds(self, tmp_path: Path):
        # arrange — the override-bypassed contract still lets work through
        assumed = ClaudeContract(version=(2, 2, 0), supported=True, assumed=True, reason=None)
        wiring = self._wiring(tmp_path, assumed)

        # act
        result = wiring.switch.execute(AccountName("y"))

        # assert
        assert result.outcome == "switched"
        assert wiring.contract_probe.probes == 1

    def test_a_dry_run_preview_never_probes(self, tmp_path: Path):
        # arrange — previews are pure reads: no mutation, no probe, no locks
        wiring = self._wiring(tmp_path, contract_for_version(None))

        # act
        result = wiring.switch.execute(AccountName("y"), dry_run=True)

        # assert
        assert result.outcome == "switched"
        assert result.dry_run is True
        assert wiring.contract_probe.probes == 0
        assert wiring.ops.acquired == []
        assert wiring.locks.acquired == []
