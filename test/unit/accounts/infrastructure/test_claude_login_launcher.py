"""Unit tests for accounts.infrastructure.claude_login_launcher and the
LoginLauncherPort it implements."""

import json
from pathlib import Path

from claude_acc_manager.accounts.application.ports import LoginLauncherPort
from claude_acc_manager.accounts.infrastructure.claude_login_launcher import (
    ClaudeLoginLauncher,
)


def make_stub(tmp_path: Path, exit_code: int) -> Path:
    """Write a fake-claude script that dumps its env and exits *exit_code*."""
    called = tmp_path / "called.json"
    stub = tmp_path / "fake-claude"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"with open({str(called)!r}, 'w', encoding='utf-8') as f:\n"
        "    json.dump({'CLAUDE_CONFIG_DIR': os.environ.get('CLAUDE_CONFIG_DIR'),\n"
        "               'ANTHROPIC_API_KEY': os.environ.get('ANTHROPIC_API_KEY')},\n"
        "              f)\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return stub


class TestLoginLauncherAdaptsThePort:
    """ClaudeLoginLauncher explicitly subclasses the port (greppable map)."""

    def test_launcher_is_a_login_launcher_port(self):
        # arrange / act
        launcher = ClaudeLoginLauncher()

        # assert
        assert isinstance(launcher, LoginLauncherPort)


class TestLaunch:
    """launch runs claude with CLAUDE_CONFIG_DIR scoped to the account dir."""

    def test_default_executable_is_path_resolved_claude(self):
        # arrange / act — ai-usagebar launches `claude` via Command::new("claude")
        launcher = ClaudeLoginLauncher()

        # assert
        assert launcher._executable == "claude"

    def test_sets_config_dir_and_strips_credentials(self, tmp_path: Path, monkeypatch) -> None:
        # arrange — ambient credentials must not short-circuit the login prompt
        monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-leak")
        stub = make_stub(tmp_path, exit_code=0)
        account_dir = tmp_path / "accounts" / "work"
        launcher = ClaudeLoginLauncher(executable=str(stub))

        # act
        ok = launcher.launch(account_dir)

        # assert
        called = json.loads((tmp_path / "called.json").read_text(encoding="utf-8"))
        assert ok is True
        assert called["CLAUDE_CONFIG_DIR"] == str(account_dir)
        assert called["ANTHROPIC_API_KEY"] is None

    def test_reports_nonzero_exit_as_failure(self, tmp_path: Path) -> None:
        # arrange
        stub = make_stub(tmp_path, exit_code=1)
        launcher = ClaudeLoginLauncher(executable=str(stub))

        # act
        ok = launcher.launch(tmp_path / "accounts" / "work")

        # assert
        assert ok is False

    def test_missing_executable_is_a_failure(self, tmp_path: Path) -> None:
        # arrange
        launcher = ClaudeLoginLauncher(executable=str(tmp_path / "no-claude"))

        # act
        ok = launcher.launch(tmp_path / "accounts" / "work")

        # assert
        assert ok is False
