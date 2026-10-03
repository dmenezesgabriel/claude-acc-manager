"""Unit tests for accounts.infrastructure.claude_login_launcher and the
LoginLauncherPort it implements."""

import json
import re
from pathlib import Path

import pytest

import claude_acc_manager.accounts.infrastructure.claude_login_launcher as claude_login_launcher
from claude_acc_manager.accounts.application.ports import LoginLauncherPort
from claude_acc_manager.accounts.infrastructure.claude_login_launcher import (
    ClaudeLoginLauncher,
)


def make_stub(
    tmp_path: Path, exit_code: int, version: str = "2.1.287", version_exit_code: int = 0
) -> Path:
    """Write a fake-claude script that answers --version and dumps its env."""
    called = tmp_path / "called.json"
    stub = tmp_path / "fake-claude"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "if '--version' in sys.argv:\n"
        f"    print('{version} (Claude Code)'); sys.exit({version_exit_code})\n"
        f"with open({str(called)!r}, 'w', encoding='utf-8') as f:\n"
        "    json.dump({'CLAUDE_CONFIG_DIR': os.environ.get('CLAUDE_CONFIG_DIR'),\n"
        "               'ANTHROPIC_API_KEY': os.environ.get('ANTHROPIC_API_KEY'),\n"
        "               'CLAUDE_SECURESTORAGE_CONFIG_DIR':\n"
        "                   os.environ.get('CLAUDE_SECURESTORAGE_CONFIG_DIR')},\n"
        "              f)\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return stub


def make_slow_version_stub(tmp_path: Path, sleep_s: float = 3.0) -> Path:
    """A fake-claude whose --version sleeps before answering."""
    stub = tmp_path / "fake-claude"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import sys, time\n"
        "if '--version' in sys.argv:\n"
        f"    time.sleep({sleep_s}); print('2.1.287 (Claude Code)'); sys.exit(0)\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return stub


def make_vanishing_stub(tmp_path: Path) -> Path:
    """A fake-claude that answers --version then deletes itself."""
    stub = tmp_path / "fake-claude"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "if '--version' in sys.argv:\n"
        "    print('2.1.287 (Claude Code)')\n"
        f"    os.remove({str(stub)!r})\n"
        "    sys.exit(0)\n"
        "sys.exit(0)\n",
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
        # arrange / act — the default executable is `claude`, resolved on PATH
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

    def test_strips_securestorage_dir_so_the_store_cannot_be_redirected(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # arrange — a set CLAUDE_SECURESTORAGE_CONFIG_DIR (2.1.x) would move
        # claude's credential store out of the account dir entirely
        monkeypatch.setenv("CLAUDE_SECURESTORAGE_CONFIG_DIR", str(tmp_path / "elsewhere"))
        stub = make_stub(tmp_path, exit_code=0)
        launcher = ClaudeLoginLauncher(executable=str(stub))

        # act
        ok = launcher.launch(tmp_path / "accounts" / "work")

        # assert
        called = json.loads((tmp_path / "called.json").read_text(encoding="utf-8"))
        assert ok is True
        assert called["CLAUDE_SECURESTORAGE_CONFIG_DIR"] is None

    def test_strips_an_empty_securestorage_dir_too(self, tmp_path: Path, monkeypatch) -> None:
        # arrange — defined-but-empty forces ~/.claude upstream (wS()), so
        # even "" must not leak into the scoped login
        monkeypatch.setenv("CLAUDE_SECURESTORAGE_CONFIG_DIR", "")
        stub = make_stub(tmp_path, exit_code=0)
        launcher = ClaudeLoginLauncher(executable=str(stub))

        # act
        ok = launcher.launch(tmp_path / "accounts" / "work")

        # assert
        called = json.loads((tmp_path / "called.json").read_text(encoding="utf-8"))
        assert ok is True
        assert called["CLAUDE_SECURESTORAGE_CONFIG_DIR"] is None

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


class TestVersionGate:
    """launch probes ``claude --version`` and refuses claude <1.0 — before
    1.0 the credential path is hardcoded ~/.claude/.credentials.json and
    CLAUDE_CONFIG_DIR cannot isolate the login (npm cli.js 0.2.126, ``NR1``).
    The login stub must never run on a refused version."""

    def test_refuses_a_pre_1_0_claude(self, tmp_path: Path) -> None:
        # arrange — 0.2.x writes .credentials.json to ~/.claude regardless
        stub = make_stub(tmp_path, exit_code=0, version="0.2.126")
        launcher = ClaudeLoginLauncher(executable=str(stub))
        expected = (
            "claude 0.2.126 cannot isolate a login: before 1.0 it ignores "
            "CLAUDE_CONFIG_DIR for .credentials.json, so the login would "
            "write the live slot — cam add requires claude >= 1.0"
        )

        # act / assert — the refusal names the detected version, verbatim
        with pytest.raises(ValueError, match=re.escape(expected)):
            launcher.launch(tmp_path / "accounts" / "work")
        # and the login itself never ran
        assert not (tmp_path / "called.json").exists()

    def test_refuses_an_unparseable_version(self, tmp_path: Path) -> None:
        # arrange — a wrapper that answers something other than semver must
        # fail closed, not proceed to a maybe-unsafe login
        stub = make_stub(tmp_path, exit_code=0, version="not-a-version")
        launcher = ClaudeLoginLauncher(executable=str(stub))
        expected = (
            "could not parse claude version from 'not-a-version (Claude Code)\\n' "
            "— expected 'X.Y.Z (Claude Code)'"
        )

        # act / assert
        with pytest.raises(ValueError, match=re.escape(expected)):
            launcher.launch(tmp_path / "accounts" / "work")
        assert not (tmp_path / "called.json").exists()

    def test_a_failed_version_probe_is_a_controlled_error(self, tmp_path: Path) -> None:
        # arrange — a claude that can't even answer --version must not launch
        stub = make_stub(tmp_path, exit_code=0, version_exit_code=3)
        launcher = ClaudeLoginLauncher(executable=str(stub))
        expected = "claude --version exited 3: 2.1.287 (Claude Code)"

        # act / assert
        with pytest.raises(ValueError, match=re.escape(expected)):
            launcher.launch(tmp_path / "accounts" / "work")
        assert not (tmp_path / "called.json").exists()

    def test_a_hanging_version_probe_times_out(self, tmp_path: Path, monkeypatch) -> None:
        # arrange — a wedged claude answers --version only after sleeping;
        # the bounded probe must convert that to a controlled error
        monkeypatch.setattr(claude_login_launcher, "_VERSION_PROBE_TIMEOUT_S", 0.2)
        stub = make_slow_version_stub(tmp_path)
        launcher = ClaudeLoginLauncher(executable=str(stub))

        # act / assert
        with pytest.raises(ValueError, match="did not answer within"):
            launcher.launch(tmp_path / "accounts" / "work")

    def test_a_vanishing_executable_reports_failure(self, tmp_path: Path) -> None:
        # arrange — the binary answers --version, then disappears before the
        # login (a TOCTOU race with an upgrade): still False, not a crash
        stub = make_vanishing_stub(tmp_path)
        launcher = ClaudeLoginLauncher(executable=str(stub))

        # act
        ok = launcher.launch(tmp_path / "accounts" / "work")

        # assert
        assert ok is False

    def test_boundary_1_0_0_launches(self, tmp_path: Path) -> None:
        # arrange — 1.0 is the first line that honors CLAUDE_CONFIG_DIR for
        # credentials (a2() in cli.js 1.0.128)
        stub = make_stub(tmp_path, exit_code=0, version="1.0.0")
        launcher = ClaudeLoginLauncher(executable=str(stub))

        # act
        ok = launcher.launch(tmp_path / "accounts" / "work")

        # assert
        assert ok is True
        assert (tmp_path / "called.json").exists()
