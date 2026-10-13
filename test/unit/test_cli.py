"""Unit tests for the cam CLI (add / remove / list / status).

User-facing output is pinned exactly — the printed line *is* the interface
(docs/architecture.md §10), so a drift in wording is a regression, not cosmetic.
"""

import json
import sys
from dataclasses import replace
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pytest
from rich.console import Console
from support.cli_rigs import (
    auto_credentials as _auto_credentials,
)
from support.cli_rigs import (
    auto_rig as _auto_rig,
)
from support.cli_rigs import (
    cache_usage as _cache_usage,
)
from support.cli_rigs import (
    config_for as _config_for,
)
from support.cli_rigs import (
    offering_use_cases as _offering_use_cases,
)
from support.cli_rigs import (
    park_account as _park,
)
from support.cli_rigs import (
    run_cli as _run,
)
from support.cli_rigs import (
    run_cli_tty as _run_tty,
)
from support.cli_rigs import (
    snap_used as _snap_used,
)
from support.cli_rigs import (
    upgrade_rig as _upgrade,
)
from support.controllable_clock import ControllableClock
from support.fake_account_dir import FakeAccountDir
from support.fake_active_slot import FakeActiveSlot
from support.fake_claude_contract import FakeClaudeContractProbe
from support.fake_credential_store import FakeCredentialStore
from support.fake_token_refresher import FakeTokenRefresher
from support.fake_tui_module import FakeTuiModule
from support.fake_upgrade_runner import FakeUpgradeRunner
from support.fake_usage_api import FakeUsageApi
from support.in_memory_account_store import InMemoryAccountStore
from support.in_memory_settings import InMemorySettings, emails_visible_settings
from support.in_memory_usage_cache import InMemoryUsageCache
from support.recording_stream import RecordingStream
from support.use_cases import (
    SEEDED_CONFIG,
    SEEDED_CREDENTIALS,
    SEEDED_SNAPSHOT,
    credentials_for,
    make_account,
    make_check_update,
    make_fetch_usage,
    make_use_cases,
    stored_credential,
)

import claude_acc_manager
from claude_acc_manager.accounts.domain.entities import QuarantineEntry
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.cli import ProcessContext, UseCases, run
from claude_acc_manager.settings.domain.settings_spec import setting_spec
from claude_acc_manager.shared.claude_contract import contract_for_version
from claude_acc_manager.update.application.ports import UpgradeToolMissingError
from claude_acc_manager.update.application.use_cases.self_upgrade import SelfUpgrade
from claude_acc_manager.update.domain.services.install_method import InstallMethod
from claude_acc_manager.usage.application.ports import AnthropicApiError
from claude_acc_manager.usage.application.use_cases.fetch_account_usage import FetchAccountUsage
from claude_acc_manager.usage.domain.usage_cache_entry import EMPTY_USAGE_CACHE_ENTRY
from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot, UsageWindow

_CREDENTIALS = SEEDED_CREDENTIALS
_CONFIG = SEEDED_CONFIG
_USAGE_SNAPSHOT = SEEDED_SNAPSHOT
_use_cases = make_use_cases
_fetch_usage = make_fetch_usage
_account = make_account
_creds_for = credentials_for
_stored_credential = stored_credential


class TestArgParsing:
    def test_no_subcommand_prints_usage_to_stderr_and_exits_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ):
        # arrange — armed but unreachable: the usage path never opens a TUI
        # (without the fake, a dispatch bug would hang on a real terminal)
        tui = FakeTuiModule()
        monkeypatch.setitem(sys.modules, "claude_acc_manager.tui", tui)

        # act
        code = _run([], _use_cases(tmp_path))

        # assert — whitespace-normalized: 3.13 rewraps argparse usage lines,
        # so the tokens are the contract, not their line breaks
        assert code == 2
        assert " ".join(capsys.readouterr().err.split()) == (
            "usage: cam [-h] [--version] "
            "{add,remove,list,status,usage,switch,disable,enable,auto,"
            "tui,doctor,watch,upgrade,config} ..."
        )
        assert tui.starts == []

    def test_rejects_a_flag_shaped_account_name(self, tmp_path: Path):
        # act / assert — argparse treats it as an unknown option
        with pytest.raises(SystemExit):
            _run(["add", "--sneaky"], _use_cases(tmp_path))


class TestVersionFlag:
    """`cam --version` — a self-report flag, dispatched like --help (pre-guard)."""

    def test_version_prints_cam_version_and_exits_0(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = _run(["--version"], _use_cases(tmp_path))

        # assert
        captured = capsys.readouterr()
        assert code == 0
        assert captured.out == f"cam {claude_acc_manager.__version__}\n"
        assert captured.err == ""

    def test_version_matches_the_installed_dist_metadata(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = _run(["--version"], _use_cases(tmp_path))

        # assert
        assert code == 0
        assert capsys.readouterr().out == f"cam {version('claude-acc-manager')}\n"

    def test_version_runs_before_the_root_guard(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act — version is a self-report like --help; the refusal gates commands
        code = run(
            ["--version"],
            _use_cases(tmp_path),
            process=ProcessContext(euid=0, in_container=False),
        )

        # assert
        assert code == 0
        assert capsys.readouterr().out.startswith("cam ")

    def test_version_falls_back_when_the_dist_is_not_installed(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        # arrange — a source checkout without an installed dist raises on lookup
        def _raise(_dist: str) -> str:
            raise PackageNotFoundError

        monkeypatch.setattr(claude_acc_manager, "version", _raise)

        # act / assert
        assert claude_acc_manager.package_version() == "0.0.0+local"


class TestBareCamTui:
    """Bare ``cam`` opens the dashboard on an interactive terminal.

    ``interactive`` on the process context means both stdin and stdout are
    TTYs — without it (scripts, pipes, cron) bare ``cam`` keeps the usage
    fallback so shell tooling never launches a full-screen app.
    """

    def test_bare_cam_launches_the_dashboard_when_interactive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # arrange — the TUI module records rather than opening a terminal
        tui = FakeTuiModule()
        monkeypatch.setitem(sys.modules, "claude_acc_manager.tui", tui)

        # act
        code = run(
            [],
            _use_cases(tmp_path),
            process=ProcessContext(euid=1000, in_container=False, interactive=True),
        )

        # assert
        assert code == 0
        assert tui.starts == ["dashboard"]

    def test_bare_cam_with_no_argv_launches_the_dashboard(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # arrange — main() passes argv=None, deferring to sys.argv like
        # argparse; a bare sys.argv still triggers the swap
        tui = FakeTuiModule()
        monkeypatch.setitem(sys.modules, "claude_acc_manager.tui", tui)
        monkeypatch.setattr(sys, "argv", ["cam"])

        # act
        code = run(
            None,
            _use_cases(tmp_path),
            process=ProcessContext(euid=1000, in_container=False, interactive=True),
        )

        # assert
        assert code == 0
        assert tui.starts == ["dashboard"]

    def test_argv_none_defers_to_sys_argv_for_the_subcommand(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # arrange — regression: argv=None once meant *every* interactive
        # command opened the TUI instead of its own handler
        tui = FakeTuiModule()
        monkeypatch.setitem(sys.modules, "claude_acc_manager.tui", tui)
        monkeypatch.setattr(sys, "argv", ["cam", "list"])

        # act
        code = run(
            None,
            _use_cases(tmp_path),
            process=ProcessContext(euid=1000, in_container=False, interactive=True),
        )

        # assert — the list handler ran; the dashboard never started
        assert code == 0
        assert tui.starts == []

    def test_bare_cam_forwards_the_tui_exit_code(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # arrange
        tui = FakeTuiModule(exit_code=7)
        monkeypatch.setitem(sys.modules, "claude_acc_manager.tui", tui)

        # act
        code = run(
            [],
            _use_cases(tmp_path),
            process=ProcessContext(euid=1000, in_container=False, interactive=True),
        )

        # assert
        assert code == 7

    def test_bare_cam_prints_usage_without_an_interactive_terminal(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # arrange — the fake is armed but must never be reached
        tui = FakeTuiModule()
        monkeypatch.setitem(sys.modules, "claude_acc_manager.tui", tui)

        # act
        code = run(
            [],
            _use_cases(tmp_path),
            process=ProcessContext(euid=1000, in_container=False, interactive=False),
        )

        # assert
        assert code == 2
        assert "usage:" in capsys.readouterr().err
        assert tui.starts == []

    def test_bare_cam_interactive_still_obeys_the_root_guard(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # arrange — the TUI performs the same mutations as `cam switch`, so
        # the §8.6 refusal gates it like any dispatched command
        tui = FakeTuiModule()
        monkeypatch.setitem(sys.modules, "claude_acc_manager.tui", tui)

        # act
        code = run(
            [],
            _use_cases(tmp_path),
            process=ProcessContext(euid=0, in_container=False, interactive=True),
        )

        # assert
        assert code == 1
        assert "refusing to run as root" in capsys.readouterr().err
        assert tui.starts == []

    def test_a_subcommand_still_dispatches_when_interactive(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        # arrange — interactive swaps only the *bare* invocation, not any argv
        tui = FakeTuiModule()
        monkeypatch.setitem(sys.modules, "claude_acc_manager.tui", tui)

        # act
        code = run(
            ["list"],
            _use_cases(tmp_path),
            process=ProcessContext(euid=1000, in_container=False, interactive=True),
        )

        # assert
        assert code == 0
        assert capsys.readouterr().out == "no accounts registered\n"
        assert tui.starts == []


class TestRootGuard:
    """euid 0 outside a container is refused before dispatch (§8.6).

    The check runs after parsing (so --help still works) and before the
    handler runs (the refusal gates command execution, not the no-command
    usage print).
    """

    def test_root_outside_a_container_is_refused(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = run(
            ["list"],
            _use_cases(tmp_path),
            process=ProcessContext(euid=0, in_container=False),
        )

        # assert
        assert code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == "error: refusing to run as root (outside a container)\n"

    def test_root_inside_a_container_is_allowed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = run(
            ["list"],
            _use_cases(tmp_path),
            process=ProcessContext(euid=0, in_container=True),
        )

        # assert
        assert code == 0
        assert capsys.readouterr().out == "no accounts registered\n"

    def test_no_subcommand_as_root_prints_usage_not_a_refusal(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act — bare cam never dispatches, so the guard doesn't fire
        code = run([], _use_cases(tmp_path), process=ProcessContext(euid=0, in_container=False))

        # assert
        assert code == 2
        assert "usage:" in capsys.readouterr().err


class TestHelpText:
    """--help output describes every command; the phrasing is pinned."""

    def _help(self, tmp_path: Path, capsys: pytest.CaptureFixture[str], *argv: str) -> str:
        with pytest.raises(SystemExit):
            _run([*argv, "--help"], _use_cases(tmp_path))
        return capsys.readouterr().out

    def test_top_level_help_lists_the_prog_description_and_commands(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        text = self._help(tmp_path, capsys)

        # assert — whitespace-normalized: 3.13 rewraps argparse usage lines,
        # so the tokens are the contract, not their line breaks
        assert " ".join(text.split()).startswith(
            "usage: cam [-h] [--version] "
            "{add,remove,list,status,usage,switch,disable,enable,auto,"
            "tui,doctor,watch,upgrade,config} ..."
        )
        assert "  --version             print the cam version and exit\n" in text
        assert "\nmanage Claude Code OAuth accounts\n" in text
        assert "    add                 register an account via an isolated claude login\n" in text
        assert "    remove              unregister an account and delete its login dir\n" in text
        assert "    list                list registered accounts\n" in text
        assert "    status              show the account the live claude slot uses\n" in text
        assert "    disable             hold an account out of automatic switching\n" in text
        assert "    enable              return a disabled account to automatic switching\n" in text
        assert "    usage               show one account's quota usage\n" in text
        assert "    switch              move the live claude login to another account\n" in text
        assert "    auto                auto-switch loop (one tick with --once)\n" in text
        assert "    tui                 interactive quota dashboard\n" in text
        assert "    doctor              diagnose cam's claude interop setup\n" in text
        assert "    watch               interactive live monitor\n" in text
        assert "    upgrade             upgrade cam via the detected installer\n" in text
        assert "    config              view or edit persisted settings\n" in text

    def test_add_and_remove_help_document_the_name_argument(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act / assert
        for command in ("add", "remove", "disable", "enable"):
            text = self._help(tmp_path, capsys, command)
            assert text.startswith(f"usage: cam {command} [-h] name\n")
            assert "  name        account name\n" in text

    def test_list_help_documents_the_json_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        text = self._help(tmp_path, capsys, "list")

        # assert
        assert text.startswith("usage: cam list [-h] [--json]\n")
        assert "  --json      emit the schema-v1 JSON payload\n" in text

    def test_status_help_documents_the_json_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        text = self._help(tmp_path, capsys, "status")

        # assert
        assert text.startswith("usage: cam status [-h] [--json]\n")
        assert "  --json      emit the schema-v1 JSON payload\n" in text

    def test_usage_help_documents_the_json_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        text = self._help(tmp_path, capsys, "usage")

        # assert
        assert text.startswith("usage: cam usage [-h] [--json] name\n")
        assert "  name        account name\n" in text
        assert "  --json      emit the schema-v1 JSON payload\n" in text

    def test_config_help_lists_every_subcommand(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        text = self._help(tmp_path, capsys, "config")

        # assert
        assert text.startswith("usage: cam config [-h] {list,get,set,unset,path} ...\n")
        assert "    list                show all effective settings\n" in text
        assert "    get                 print one setting's effective value\n" in text
        assert "    set                 validate and persist one setting\n" in text
        assert "    unset               revert one setting to its default\n" in text
        assert "    path                print the settings.json location\n" in text

    def test_config_list_help_documents_the_json_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        text = self._help(tmp_path, capsys, "config", "list")

        # assert
        assert text.startswith("usage: cam config list [-h] [--json]\n")
        assert "  --json      emit the schema-v1 JSON payload\n" in text

    def test_config_get_help_documents_key_and_json(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        text = self._help(tmp_path, capsys, "config", "get")

        # assert
        assert text.startswith("usage: cam config get [-h] [--json] KEY\n")
        assert "  KEY         dotted key, e.g. autoswitch.threshold\n" in text
        assert "  --json      emit the schema-v1 JSON payload\n" in text

    def test_config_set_help_documents_key_and_value(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        text = self._help(tmp_path, capsys, "config", "set")

        # assert
        assert text.startswith("usage: cam config set [-h] KEY VALUE\n")

    def test_config_unset_and_path_help(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # act / assert
        assert self._help(tmp_path, capsys, "config", "unset").startswith(
            "usage: cam config unset [-h] KEY\n"
        )
        assert self._help(tmp_path, capsys, "config", "path").startswith(
            "usage: cam config path [-h]\n"
        )

    def test_upgrade_help_documents_the_optional_target(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        text = self._help(tmp_path, capsys, "upgrade")

        # assert — VERSION is optional; uv-only pinning is the documented caveat
        assert text.startswith("usage: cam upgrade [-h] [VERSION]\n")
        assert "  VERSION     pin the upgrade to this release (uv installs only)\n" in text

    def test_auto_help_documents_every_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        text = self._help(tmp_path, capsys, "auto")

        # assert
        assert text.startswith(
            "usage: cam auto [-h] [--once] [--interval SECONDS] [--threshold PCT]\n"
        )
        assert "  --once                evaluate once, maybe switch, and exit" in text
        assert "  --interval SECONDS    poll interval in loop mode\n" in text
        assert "  --threshold PCT       switch when the active's binding window" in text
        assert "  --cooldown SECONDS    minimum time between proactive switches\n" in text
        assert "  --strategy {best,next-available}\n" in text
        assert "target selection strategy\n" in text
        assert (
            "Runs a foreground polling loop; --once evaluates once and reports the "
            "outcome\nin the exit code (0 switched, 1 error, 2 no action, 3 blocked). "
            "Defaults come\nfrom settings.json; flags override them.\n"
        ) in text
        assert "  --dry-run             report decisions without switching" in text
        assert "  --json                emit one JSON event per line\n" in text


class TestTuiEntryPoints:
    """`cam tui` / `cam watch` hand off to the TUI runner with a start screen."""

    @staticmethod
    def _capture_run(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
        """Swap the TUI runner for a recorder — the real one owns the terminal."""
        captured: dict[str, object] = {}

        def fake_run(use_cases: UseCases, *, start: str) -> int:
            captured["start"] = start
            captured["use_cases"] = use_cases
            return 0

        import claude_acc_manager.tui

        monkeypatch.setattr(claude_acc_manager.tui, "run", fake_run)
        return captured

    def test_tui_opens_the_dashboard(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        captured = self._capture_run(monkeypatch)
        use_cases = _use_cases(tmp_path)

        code = _run(["tui"], use_cases)

        assert code == 0
        assert captured["start"] == "dashboard"
        assert captured["use_cases"] is use_cases

    def test_watch_opens_the_watch_screen(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        captured = self._capture_run(monkeypatch)
        use_cases = _use_cases(tmp_path)

        code = _run(["watch"], use_cases)

        assert code == 0
        assert captured["start"] == "watch"
        assert captured["use_cases"] is use_cases


class TestConfigCommand:
    """`cam config` — the persisted settings surface."""

    def test_bare_config_lists_all_keys_with_defaults_marked(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange / act
        code = _run(["config"], _use_cases(tmp_path))

        # assert
        out = capsys.readouterr().out
        assert code == 0
        assert "autoswitch.threshold" in out
        assert "90" in out
        assert "privacy.redactEmails" in out
        assert "updates.mode" in out
        assert out.count("(default)") == 7

    def test_list_marks_only_set_keys(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange
        use_cases = _use_cases(tmp_path)
        _run(["config", "set", "autoswitch.threshold", "80"], use_cases)
        capsys.readouterr()

        # act
        code = _run(["config", "list"], use_cases)

        # assert
        out = capsys.readouterr().out
        assert code == 0
        threshold_line = next(
            line for line in out.splitlines() if line.startswith("autoswitch.threshold")
        )
        assert "80" in threshold_line and "(default)" not in threshold_line
        assert out.count("(default)") == 6

    def test_get_prints_the_effective_value(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange / act
        code = _run(["config", "get", "autoswitch.threshold"], _use_cases(tmp_path))

        # assert
        assert code == 0
        assert capsys.readouterr().out.strip() == "90"

    def test_get_json_reports_is_set(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange
        use_cases = _use_cases(tmp_path)
        _run(["config", "set", "autoswitch.threshold", "80"], use_cases)
        capsys.readouterr()

        # act
        code = _run(["config", "get", "--json", "autoswitch.threshold"], use_cases)

        # assert
        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload == {
            "schemaVersion": 1,
            "key": "autoswitch.threshold",
            "value": 80.0,
            "isSet": True,
        }

    def test_list_json_wraps_every_key(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange / act
        code = _run(["config", "list", "--json"], _use_cases(tmp_path))

        # assert
        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload["schemaVersion"] == 1
        assert payload["path"].endswith("settings.json")
        keys = {row["key"] for row in payload["settings"]}
        assert keys == {
            "autoswitch.threshold",
            "autoswitch.intervalSeconds",
            "autoswitch.cooldownSeconds",
            "autoswitch.hysteresisPct",
            "autoswitch.strategy",
            "privacy.redactEmails",
            "updates.mode",
        }
        assert all(row["isSet"] is False for row in payload["settings"])
        values = {row["key"]: row["value"] for row in payload["settings"]}
        assert values == {
            "autoswitch.threshold": 90.0,
            "autoswitch.intervalSeconds": 60.0,
            "autoswitch.cooldownSeconds": 300.0,
            "autoswitch.hysteresisPct": 10.0,
            "autoswitch.strategy": "best",
            "privacy.redactEmails": True,
            "updates.mode": "notify",
        }

    def test_set_persists_and_confirms(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange
        use_cases = _use_cases(tmp_path)

        # act
        code = _run(["config", "set", "autoswitch.threshold", "80"], use_cases)

        # assert
        assert code == 0
        assert capsys.readouterr().out.strip() == "autoswitch.threshold = 80"
        assert use_cases.load_settings.execute().threshold == 80.0

    def test_set_unknown_key_errors(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange / act
        code = _run(["config", "set", "autoswitch.bogus", "1"], _use_cases(tmp_path))

        # assert
        assert code == 1
        assert "unknown setting" in capsys.readouterr().err

    def test_set_out_of_range_errors(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange / act
        code = _run(["config", "set", "autoswitch.threshold", "999"], _use_cases(tmp_path))

        # assert
        assert code == 1
        assert "between 50 and 99.9" in capsys.readouterr().err

    def test_unset_reverts_to_the_default(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange
        use_cases = _use_cases(tmp_path)
        _run(["config", "set", "autoswitch.threshold", "80"], use_cases)
        capsys.readouterr()

        # act
        code = _run(["config", "unset", "autoswitch.threshold"], use_cases)

        # assert
        assert code == 0
        assert "autoswitch.threshold unset (default: 90)" in capsys.readouterr().out
        assert use_cases.load_settings.execute().threshold == 90.0

    def test_unset_when_not_set_reports_nothing_to_do(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange / act
        code = _run(["config", "unset", "autoswitch.threshold"], _use_cases(tmp_path))

        # assert
        assert code == 0
        assert "is not set; nothing to do" in capsys.readouterr().err

    def test_path_prints_the_settings_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange / act
        code = _run(["config", "path"], _use_cases(tmp_path))

        # assert
        out = capsys.readouterr().out.strip()
        assert code == 0
        assert out.endswith("settings.json")


# -- cam auto -------------------------------------------------------------------

_STAMP = "13:46:40"  # the use-cases rig's pinned clock (epoch 1_000_000)


class TestHumanStyling:
    """ANSI chrome over the pinned wording — only under a color console."""

    def test_the_active_list_marker_is_accented(self, tmp_path: Path):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        store.set_active(AccountName("work"))

        # act
        code, out, _ = _run_tty(
            ["list"],
            _use_cases(tmp_path, store=store, settings=emails_visible_settings(tmp_path)),
        )

        # assert — bold-cyan `*`; the literal tab survives inside the row
        assert code == 0
        assert "\x1b[1;36m*\x1b[0m" in out
        assert "\twork@example.com" in out

    def test_disabled_and_quarantined_flags_carry_severity(self, tmp_path: Path):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        store.upsert(_account("personal"))
        store.set_enabled(AccountName("personal"), False)
        store.set_quarantined(
            QuarantineEntry("work", "permanent_auth_error", "2026-10-01T00:00:00Z", "sha256:x")
        )

        # act
        code, out, _ = _run_tty(["list"], _use_cases(tmp_path, store=store))

        # assert — dim [disabled], yellow [quarantined]
        assert code == 0
        assert "\x1b[2m [disabled]\x1b[0m" in out
        assert "\x1b[33m [quarantined]\x1b[0m" in out

    def test_usage_pcts_ride_the_severity_ramp(self, tmp_path: Path):
        # arrange — five_hour at 95% sits over the CRIT edge
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        snapshot = UsageSnapshot(
            five_hour=UsageWindow(pct=95.0, resets_at=None),
            seven_day=UsageWindow(pct=27.0, resets_at=None),
            scoped=(),
        )
        credentials = FakeCredentialStore(credentials={"work": _stored_credential()})
        fetch_usage = _fetch_usage(
            usage_api=FakeUsageApi(snapshot=snapshot), credentials=credentials
        )

        # act
        code, out, _ = _run_tty(
            ["usage", "work"], _use_cases(tmp_path, store=store, fetch_usage=fetch_usage)
        )

        # assert — 95% red, 27% green; the labels stay plain
        assert code == 0
        assert "\x1b[31m95%\x1b[0m" in out
        assert "\x1b[32m27%\x1b[0m" in out

    def test_an_error_line_gets_a_red_prefix_on_stderr(self, tmp_path: Path):
        # act — an unknown account raises through the handled-error path
        code, _, err = _run_tty(["usage", "ghost"], _use_cases(tmp_path))

        # assert — the `error:` prefix is red, the message untouched
        assert code == 1
        assert err == "\x1b[31merror:\x1b[0m no such account: 'ghost'\n"

    def test_a_confirmation_is_bold(self, tmp_path: Path):
        # act
        code, out, _ = _run_tty(["add", "work"], _use_cases(tmp_path))

        # assert
        assert code == 0
        assert "\x1b[1madded account 'work'\x1b[0m" in out

    def test_a_real_switch_confirmation_is_bold(self, tmp_path: Path):
        # arrange — x live, y parked (the standard switch rig)
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))

        # act
        code, out, _ = _run_tty(
            ["switch", "y"], _use_cases(tmp_path, store=store, reader=reader, slot=slot)
        )

        # assert — the success line is a confirmation: bold
        assert code == 0
        assert "\x1b[1mswitched to 'y' (was 'x')\x1b[0m" in out

    def test_the_error_prefix_stays_red_with_a_piped_stdout(self, tmp_path: Path):
        # arrange — stdout piped (no color), stderr a tty (color): the
        # fragment must follow the *err* console's detection
        err_stream = RecordingStream()

        # act
        code = run(
            ["usage", "ghost"],
            _use_cases(tmp_path),
            process=ProcessContext(euid=1000, in_container=False),
            console=Console(file=RecordingStream()),
            err_console=Console(file=err_stream, force_terminal=True),
        )

        # assert — red survives stdout losing its color
        assert code == 1
        assert err_stream.getvalue() == "\x1b[31merror:\x1b[0m no such account: 'ghost'\n"

    def test_a_remove_confirmation_is_bold(self, tmp_path: Path):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))

        # act
        code, out, _ = _run_tty(["remove", "work"], _use_cases(tmp_path, store=store))

        # assert
        assert code == 0
        assert "\x1b[1mremoved account 'work'\x1b[0m" in out

    def test_a_disable_confirmation_is_bold(self, tmp_path: Path):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))

        # act
        code, out, _ = _run_tty(["disable", "work"], _use_cases(tmp_path, store=store))

        # assert
        assert code == 0
        assert "\x1b[1mdisabled account 'work'\x1b[0m" in out

    def test_config_set_and_unset_confirmations_are_bold(self, tmp_path: Path):
        # arrange — one instance: unset must see the set
        use_cases = _use_cases(tmp_path)

        # act
        code_set, out_set, _ = _run_tty(["config", "set", "autoswitch.threshold", "80"], use_cases)
        code_unset, out_unset, _ = _run_tty(["config", "unset", "autoswitch.threshold"], use_cases)

        # assert
        assert code_set == 0
        assert "\x1b[1mautoswitch.threshold = 80\x1b[0m" in out_set
        assert code_unset == 0
        assert "\x1b[1mautoswitch.threshold unset (default: 90)\x1b[0m" in out_unset

    def test_usage_unknown_and_the_quarantine_note_carry_severity(self, tmp_path: Path):
        # arrange — the parked account's expired token gets invalid_grant
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        reader = FakeAccountDir()
        parked = {"claudeAiOauth": {"accessToken": "at", "refreshToken": "rt-dead"}}
        reader.put(
            store.account_dir(AccountName("work")),
            credentials=parked,
            config=_config_for("acc-x"),
        )
        credentials = FakeCredentialStore(
            credentials={"work": _stored_credential(expires_at_ms=0.0)}
        )
        fetch_usage = _fetch_usage(
            credentials=credentials,
            refresher=FakeTokenRefresher(error=AnthropicApiError(400, "invalid_grant")),
        )

        # act
        code, out, _ = _run_tty(
            ["usage", "work"], _use_cases(tmp_path, store=store, fetch_usage=fetch_usage)
        )

        # assert — unknown reads dim, the quarantine note yellow
        assert code == 0
        assert "\x1b[2musage unknown: invalid_grant\x1b[0m" in out
        assert (
            "\x1b[33mquarantined 'work': the provider permanently rejected "
            "its refresh token\x1b[0m" in out
        )

    def test_a_stale_note_reads_dim(self, tmp_path: Path):
        # arrange — a frozen last_good served after a 429
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(EMPTY_USAGE_CACHE_ENTRY, last_good=_USAGE_SNAPSHOT, fetched_at_s=999_800.0),
        )
        credentials = FakeCredentialStore(credentials={"work": _stored_credential()})
        fetch_usage = FetchAccountUsage(
            FakeUsageApi(error=AnthropicApiError(429, None)),
            FakeTokenRefresher(),
            credentials,
            cache,
            ControllableClock(now_epoch_s=1_000_000.0),
            FakeClaudeContractProbe(contract_for_version((2, 1, 288))),
            threshold=90.0,
        )

        # act
        code, out, _ = _run_tty(
            ["usage", "work"], _use_cases(tmp_path, store=store, fetch_usage=fetch_usage)
        )

        # assert
        assert code == 0
        assert "\x1b[2m(stale: http-429)\x1b[0m" in out

    def test_a_skipped_candidate_reads_dim(self, tmp_path: Path):
        # arrange — y is at its limit (0 headroom); z still has room
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        _park(store, reader, "z")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))
        cache = InMemoryUsageCache()
        _cache_usage(cache, "y", 100.0)
        _cache_usage(cache, "z", 30.0)

        # act
        code, out, _ = _run_tty(
            ["switch", "--strategy", "next-available"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot, usage_cache=cache),
        )

        # assert
        assert code == 0
        assert "\x1b[2mskipped 'y': at-limit\x1b[0m" in out

    def test_a_preserved_unmanaged_login_reads_dim(self, tmp_path: Path):
        # arrange — the live slot holds a foreign login, not a managed account
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        slot = FakeActiveSlot(credentials=_creds_for("foreign"), config=_config_for("acc-foreign"))

        # act
        code, out, _ = _run_tty(
            ["switch", "x"], _use_cases(tmp_path, store=store, reader=reader, slot=slot)
        )

        # assert
        assert code == 0
        assert (
            "\x1b[2mthe previous unmanaged login was preserved under "
            "/unclaimed/fake-1.json\x1b[0m" in out
        )

    def test_a_quarantined_wiped_credential_reads_yellow(self, tmp_path: Path):
        # arrange — x's live tokens were wiped in place by an invalid_grant
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        _park(store, reader, "y")
        wiped = {"claudeAiOauth": {"accessToken": "", "refreshToken": "", "expiresAt": 1}}
        slot = FakeActiveSlot(credentials=wiped, config=_config_for("acc-x"))

        # act
        code, out, _ = _run_tty(
            ["switch", "y"], _use_cases(tmp_path, store=store, reader=reader, slot=slot)
        )

        # assert
        assert code == 0
        assert "\x1b[33mquarantined the wiped credential of 'x'\x1b[0m" in out


class TestUpgradeCommand:
    """`cam upgrade [target]` — delegate to the installer, or print the manual path."""

    def test_a_uv_install_delegates_and_exits_with_the_managers_code(self, tmp_path: Path):
        # arrange
        use_cases, runner = _upgrade(tmp_path, InstallMethod.UV)

        # act
        code = _run(["upgrade"], use_cases)

        # assert — argv verbatim, rc 0 verbatim; the child's own output spoke
        assert code == 0
        assert runner.calls == [["uv", "tool", "upgrade", "claude-acc-manager"]]

    def test_a_pipx_install_delegates_through_pipx_upgrade(self, tmp_path: Path):
        # arrange
        use_cases, runner = _upgrade(tmp_path, InstallMethod.PIPX)

        # act
        code = _run(["upgrade"], use_cases)

        # assert
        assert code == 0
        assert runner.calls == [["pipx", "upgrade", "claude-acc-manager"]]

    def test_a_target_pins_the_uv_upgrade(self, tmp_path: Path):
        # arrange — `uv tool upgrade` accepts a name==version specifier
        use_cases, runner = _upgrade(tmp_path, InstallMethod.UV)

        # act
        code = _run(["upgrade", "1.2.0"], use_cases)

        # assert
        assert code == 0
        assert runner.calls == [["uv", "tool", "upgrade", "claude-acc-manager==1.2.0"]]

    def test_the_managers_nonzero_code_is_the_commands(self, tmp_path: Path):
        # a failed upgrade keeps its rc — the child's stderr already said why
        use_cases, _ = _upgrade(tmp_path, InstallMethod.UV, FakeUpgradeRunner(returncode=2))

        # act / assert
        assert _run(["upgrade"], use_cases) == 2

    def test_an_unknown_install_prints_the_manual_list_and_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        use_cases, runner = _upgrade(tmp_path, InstallMethod.UNKNOWN)

        # act
        code = _run(["upgrade"], use_cases)

        # assert — nothing ran; the manual paths are claude-swap's list
        captured = capsys.readouterr()
        assert code == 1
        assert runner.calls == []
        assert captured.out == ""
        assert captured.err == (
            "error: could not detect how cam was installed "
            "(looked for a uv tool or pipx venv)\n"
            f"  sys.prefix:     {sys.prefix}\n"
            f"  sys.executable: {sys.executable}\n"
            "to upgrade manually, run one of:\n"
            "  uv tool upgrade claude-acc-manager\n"
            "  pipx upgrade claude-acc-manager\n"
            f"  {sys.executable} -m pip install --upgrade claude-acc-manager\n"
            "if cam came from a git checkout, `git pull` upgrades it instead\n"
        )

    def test_a_vcs_install_points_back_at_its_source(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — a git/path receipt: `uv tool upgrade` would re-resolve the
        # ref, not the release, so delegation is refused outright
        use_cases, _ = _upgrade(tmp_path, InstallMethod.VCS)

        # act
        code = _run(["upgrade"], use_cases)

        # assert
        captured = capsys.readouterr()
        assert code == 1
        assert captured.out == ""
        assert captured.err == (
            "error: cam was installed from a source checkout, not a package index\n"
            "  upgrade by re-installing from that source "
            "(e.g. `git pull` in the checkout)\n"
        )

    def test_a_pipx_install_cannot_pin_a_target(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — `pipx upgrade` takes no version specifier
        use_cases, runner = _upgrade(tmp_path, InstallMethod.PIPX)

        # act
        code = _run(["upgrade", "1.2.0"], use_cases)

        # assert — the refusal names the pipx pin path verbatim
        captured = capsys.readouterr()
        assert code == 1
        assert runner.calls == []
        assert captured.out == ""
        assert captured.err == (
            "error: `pipx upgrade` cannot pin a version\n"
            "  run `pipx install --force claude-acc-manager==1.2.0` for that release,\n"
            "  or a bare `cam upgrade` for the latest\n"
        )

    def test_a_missing_manager_names_it_on_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — UpgradeToolMissingError is the port's named FileNotFoundError
        runner = FakeUpgradeRunner(
            error=UpgradeToolMissingError("upgrade tool 'uv' is not on PATH")
        )
        use_cases, _ = _upgrade(tmp_path, InstallMethod.UV, runner)

        # act
        code = _run(["upgrade"], use_cases)

        # assert
        captured = capsys.readouterr()
        assert code == 1
        assert captured.out == ""
        assert captured.err == "error: upgrade tool 'uv' is not on PATH\n"

    def test_the_error_prefix_stays_red_with_a_piped_stdout(self, tmp_path: Path):
        # arrange — stdout piped (no color), stderr a tty (color): the
        # fragment must follow the *err* console's detection
        err_stream = RecordingStream()
        runner = FakeUpgradeRunner(
            error=UpgradeToolMissingError("upgrade tool 'uv' is not on PATH")
        )
        use_cases, _ = _upgrade(tmp_path, InstallMethod.UV, runner)

        # act
        code = run(
            ["upgrade"],
            use_cases,
            process=ProcessContext(euid=1000, in_container=False),
            console=Console(file=RecordingStream()),
            err_console=Console(file=err_stream, force_terminal=True),
        )

        # assert — red survives stdout losing its color
        assert code == 1
        assert err_stream.getvalue() == "\x1b[31merror:\x1b[0m upgrade tool 'uv' is not on PATH\n"

    def test_the_manual_path_error_stays_red_with_a_piped_stdout(self, tmp_path: Path):
        # arrange — same asymmetric rig on the _print_manual_upgrade site
        err_stream = RecordingStream()
        use_cases, _ = _upgrade(tmp_path, InstallMethod.UNKNOWN)

        # act
        code = run(
            ["upgrade"],
            use_cases,
            process=ProcessContext(euid=1000, in_container=False),
            console=Console(file=RecordingStream()),
            err_console=Console(file=err_stream, force_terminal=True),
        )

        # assert
        assert code == 1
        assert err_stream.getvalue().startswith("\x1b[31merror:\x1b[0m ")


_NOTICE = "cam 9.9.9 is available (you have 1.0.0) — run `cam upgrade`"


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
