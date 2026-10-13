"""Update notice + auto-apply — when a newer release is announced or applied.

The notice is a stderr line pinned exactly; auto-apply delegates to the
self-upgrade use case and still falls back to the notice on failure.
"""

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from support.cli_rigs import NOTICE as _NOTICE
from support.cli_rigs import STAMP as _STAMP
from support.cli_rigs import auto_credentials as _auto_credentials
from support.cli_rigs import auto_rig as _auto_rig
from support.cli_rigs import offering_use_cases as _offering_use_cases
from support.cli_rigs import run_cli as _run
from support.cli_rigs import snap_used as _snap_used
from support.fake_tui_module import FakeTuiModule
from support.fake_upgrade_runner import FakeUpgradeRunner
from support.in_memory_settings import InMemorySettings
from support.use_cases import make_check_update, make_use_cases

from claude_acc_manager.cli import UseCases
from claude_acc_manager.settings.domain.settings_spec import setting_spec
from claude_acc_manager.update.application.use_cases.self_upgrade import SelfUpgrade
from claude_acc_manager.update.domain.services.install_method import InstallMethod

_use_cases = make_use_cases


class TestUpdateNotice:
    """The post-command release notice — stderr only, once per surface."""

    def test_a_newer_release_prints_the_notice_to_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        use_cases = _offering_use_cases(tmp_path)

        # act
        code = _run(["list"], use_cases)

        # assert — the notice rides stderr; stdout keeps the command output
        captured = capsys.readouterr()
        assert code == 0
        assert captured.out == "no accounts registered\n"
        assert captured.err == f"{_NOTICE}\n"

    def test_no_offer_prints_nothing(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # act / assert — feed reports the running version, so nothing to say
        code = _run(["list"], _use_cases(tmp_path, check_update=make_check_update(latest="1.0.0")))

        captured = capsys.readouterr()
        assert code == 0
        assert captured.err == ""

    @pytest.mark.parametrize("argv", [["list", "--json"], ["auto", "--once", "--json"]])
    def test_json_modes_suppress_the_notice(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], argv: list[str]
    ):
        # act — machine surfaces own the channels; the check never fires a notice
        _run(argv, _offering_use_cases(tmp_path))

        # assert — stderr stays silent; stdout purity is pinned elsewhere
        assert capsys.readouterr().err == ""

    @pytest.mark.parametrize("argv", [["upgrade"], ["auto", "--once"]])
    def test_commands_with_their_own_surface_suppress_the_notice(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        argv: list[str],
    ):
        # arrange — `upgrade` IS the remedy; `auto` emits the event line instead
        use_cases = _offering_use_cases(
            tmp_path, self_upgrade=SelfUpgrade(FakeUpgradeRunner(), method=InstallMethod.UV)
        )

        # act
        _run(argv, use_cases)

        # assert
        assert capsys.readouterr().err == ""

    @pytest.mark.parametrize("argv", [["tui"], ["watch"]])
    def test_tui_commands_suppress_the_notice(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
        argv: list[str],
    ):
        # arrange — the TUI's mount-time toast is this install's surface
        tui = FakeTuiModule()
        monkeypatch.setitem(sys.modules, "claude_acc_manager.tui", tui)

        # act
        _run(argv, _offering_use_cases(tmp_path))

        # assert
        assert capsys.readouterr().err == ""

    def test_version_and_bare_usage_never_notice(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act / assert — both return before the dispatch hook runs
        _run(["--version"], _offering_use_cases(tmp_path))
        assert capsys.readouterr().err == ""

        _run([], _offering_use_cases(tmp_path))
        assert _NOTICE not in capsys.readouterr().err

    def test_a_failed_command_prints_no_notice(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act — the KeyError path returns before the notice point
        code = _run(["remove", "ghost"], _offering_use_cases(tmp_path))

        # assert — the error line stands alone
        captured = capsys.readouterr()
        assert code == 1
        assert captured.err == "error: no such account: 'ghost'\n"

    def test_updates_mode_off_silences_the_notice(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        _run(
            ["list"],
            _use_cases(tmp_path, check_update=make_check_update(latest="9.9.9", mode="off")),
        )

        # assert
        assert capsys.readouterr().err == ""

    def test_the_env_kill_switch_silences_the_notice(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        use_cases = _use_cases(
            tmp_path,
            check_update=make_check_update(latest="9.9.9", env={"CAM_DISABLE_UPDATE_CHECK": "1"}),
        )

        # act
        _run(["list"], use_cases)

        # assert
        assert capsys.readouterr().err == ""


class TestUpdateAutoApply:
    """``updates.mode=auto`` — a PATCH offer delegates; anything else notifies."""

    def _auto_use_cases(
        self,
        tmp_path: Path,
        *,
        latest: str,
        method: InstallMethod = InstallMethod.UV,
        runner: FakeUpgradeRunner | None = None,
    ) -> tuple[UseCases, FakeUpgradeRunner]:
        """An auto-mode rig: settings + check agree, runner records delegation."""
        settings = InMemorySettings(tmp_path)
        settings.set_value(setting_spec("updates.mode"), "auto")
        runner = runner if runner is not None else FakeUpgradeRunner()
        use_cases = _use_cases(
            tmp_path,
            settings=settings,
            check_update=make_check_update(latest=latest, mode="auto"),
            self_upgrade=SelfUpgrade(runner, method=method),
        )
        return use_cases, runner

    def test_a_patch_offer_delegates_the_upgrade(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — 1.0.0 → 1.0.1 is a patch jump
        use_cases, runner = self._auto_use_cases(tmp_path, latest="1.0.1")

        # act
        code = _run(["list"], use_cases)

        # assert — the manager ran; the command's own rc stands
        captured = capsys.readouterr()
        assert code == 0
        assert runner.calls == [["uv", "tool", "upgrade", "claude-acc-manager"]]
        assert captured.err == ("cam 1.0.1 is available (you have 1.0.0) — applying patch update\n")

    def test_a_minor_offer_only_notifies(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange — 1.0.0 → 1.1.0 is minor; auto never self-applies it
        use_cases, runner = self._auto_use_cases(tmp_path, latest="1.1.0")

        # act
        _run(["list"], use_cases)

        # assert
        captured = capsys.readouterr()
        assert runner.calls == []
        assert captured.err == "cam 1.1.0 is available (you have 1.0.0) — run `cam upgrade`\n"

    def test_notify_mode_never_applies(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange — a patch offer under the default notify mode
        runner = FakeUpgradeRunner()
        use_cases = _use_cases(
            tmp_path,
            check_update=make_check_update(latest="1.0.1"),
            self_upgrade=SelfUpgrade(runner, method=InstallMethod.UV),
        )

        # act
        _run(["list"], use_cases)

        # assert
        captured = capsys.readouterr()
        assert runner.calls == []
        assert captured.err == "cam 1.0.1 is available (you have 1.0.0) — run `cam upgrade`\n"

    def test_an_undelegable_install_falls_back_to_the_notice(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — VCS/unknown methods refuse delegation
        use_cases, runner = self._auto_use_cases(
            tmp_path, latest="1.0.1", method=InstallMethod.UNKNOWN
        )

        # act
        code = _run(["list"], use_cases)

        # assert — nothing ran; the attempted apply degrades to the notice
        captured = capsys.readouterr()
        assert code == 0
        assert runner.calls == []
        assert captured.err == (
            "cam 1.0.1 is available (you have 1.0.0) — applying patch update\n"
            "cam 1.0.1 is available (you have 1.0.0) — run `cam upgrade`\n"
        )

    def test_a_failed_delegation_falls_back_to_the_notice(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — a spawn failure must never break the command that ran
        use_cases, runner = self._auto_use_cases(
            tmp_path, latest="1.0.1", runner=FakeUpgradeRunner(error=OSError("spawn failed"))
        )

        # act
        code = _run(["list"], use_cases)

        # assert
        captured = capsys.readouterr()
        assert code == 0
        assert captured.err == (
            "cam 1.0.1 is available (you have 1.0.0) — applying patch update\n"
            "cam 1.0.1 is available (you have 1.0.0) — run `cam upgrade`\n"
        )


class TestAutoUpdateEvent:
    """``cam auto``'s update surface — one event line per run, on stdout."""

    def _rig(self, tmp_path: Path, latest: str | None = "9.9.9") -> UseCases:
        """The two-account rig plus a check offering *latest* (None = no offer)."""
        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(50.0), "at-y": _snap_used(20.0)},
            credentials=_auto_credentials("x", "y"),
        )
        return replace(use_cases, check_update=make_check_update(latest=latest))

    def test_an_offer_emits_the_update_line_before_the_tick(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = _run(["auto", "--once"], self._rig(tmp_path))

        # assert — the notice rides the event stream; the tick outcome stands
        assert code == 2
        assert capsys.readouterr().out.splitlines()[0] == f"{_STAMP}  {_NOTICE}"

    def test_an_offer_emits_a_jsonl_event(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # act
        code = _run(["auto", "--once", "--json"], self._rig(tmp_path))

        # assert — machine consumers get the structured row instead
        assert code == 2
        first = json.loads(capsys.readouterr().out.splitlines()[0])
        assert first == {
            "schemaVersion": 1,
            "event": "update-available",
            "ts": "1970-01-12T13:46:40Z",
            "currentVersion": "1.0.0",
            "latestVersion": "9.9.9",
            "releaseType": "major",
        }

    def test_no_offer_emits_no_event(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # act — feed at parity with the running version
        code = _run(["auto", "--once", "--json"], self._rig(tmp_path, latest=None))

        # assert — no update row anywhere in the stream
        assert code == 2
        kinds = [json.loads(line)["event"] for line in capsys.readouterr().out.splitlines()]
        assert "update-available" not in kinds
