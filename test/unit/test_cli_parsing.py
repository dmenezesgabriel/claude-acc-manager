"""CLI surface mechanics — argv shape, ``--version``, root guard, help text.

User-facing output is pinned exactly — the printed line *is* the interface
(docs/architecture.md §10), so a drift in wording is a regression, not cosmetic.
"""

import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pytest
from support.cli_rigs import run_cli as _run
from support.fake_tui_module import FakeTuiModule
from support.use_cases import make_use_cases

import claude_acc_manager
from claude_acc_manager.cli import ProcessContext, run

_use_cases = make_use_cases


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
