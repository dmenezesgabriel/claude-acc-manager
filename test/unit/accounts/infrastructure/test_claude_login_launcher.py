"""Unit tests for accounts.infrastructure.claude_login_launcher and the
LoginLauncherPort it implements."""

import json
import re
from pathlib import Path

import pytest

from claude_acc_manager.accounts.application.ports import LoginLauncherPort
from claude_acc_manager.accounts.infrastructure.claude_login_launcher import (
    ClaudeLoginLauncher,
)
from claude_acc_manager.shared.claude_contract import (
    CAM_ASSUME_CLAUDE_CONTRACT,
    UnsupportedClaudeVersionError,
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
        "    json.dump(dict(os.environ), f)\n"
        f"sys.exit({exit_code})\n",
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
        assert "ANTHROPIC_API_KEY" not in called

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
        assert "CLAUDE_SECURESTORAGE_CONFIG_DIR" not in called

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
        assert "CLAUDE_SECURESTORAGE_CONFIG_DIR" not in called

    def test_reports_nonzero_exit_as_failure(self, tmp_path: Path) -> None:
        # arrange
        stub = make_stub(tmp_path, exit_code=1)
        launcher = ClaudeLoginLauncher(executable=str(stub))

        # act
        ok = launcher.launch(tmp_path / "accounts" / "work")

        # assert
        assert ok is False


class TestEnvSanitization:
    """Every ambient var the 2.1.288 linux-x64 binary reads that could
    redirect the scoped login, supply credentials, inject identity, or move
    the store must never reach the child env."""

    @pytest.mark.parametrize(
        "var",
        [
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_BEDROCK_BASE_URL",
            "ANTHROPIC_FOUNDRY_BASE_URL",
            "ANTHROPIC_GOOGLE_CLOUD_BASE_URL",
            "ANTHROPIC_VERTEX_BASE_URL",
            "CLAUDE_CODE_GB_BASE_URL",
            "CLAUDE_CODE_MEMORY_API_BASE_URL",
            "CLAUDE_LOCAL_OAUTH_API_BASE",
            "CLAUDE_LOCAL_OAUTH_APPS_BASE",
            "CLAUDE_LOCAL_OAUTH_CONSOLE_BASE",
            "USE_LOCAL_OAUTH",
        ],
    )
    def test_strips_endpoint_redirect_vars(self, tmp_path: Path, monkeypatch, var: str) -> None:
        # arrange — ambient redirects would route the login's OAuth/API
        # traffic away from Anthropic's hosts
        monkeypatch.setenv(var, "https://elsewhere.invalid")
        stub = make_stub(tmp_path, exit_code=0)
        launcher = ClaudeLoginLauncher(executable=str(stub))

        # act
        assert launcher.launch(tmp_path / "accounts" / "work") is True

        # assert
        called = json.loads((tmp_path / "called.json").read_text(encoding="utf-8"))
        assert var not in called

    @pytest.mark.parametrize(
        "var",
        [
            "CLAUDE_CODE_OAUTH_REFRESH_TOKEN",
            "CLAUDE_CODE_SESSION_ACCESS_TOKEN",
            "CLAUDE_CODE_OAUTH_CLIENT_ID",
            "CLAUDE_CODE_OAUTH_SCOPES",
            "ANTHROPIC_IDENTITY_TOKEN",
            "ANTHROPIC_IDENTITY_TOKEN_FILE",
            "CLAUDE_TRUSTED_DEVICE_TOKEN",
            "CLAUDE_SESSION_INGRESS_TOKEN_FILE",
            "CLAUDE_CODE_GATEWAY_TOKEN",
            "CLAUDE_CODE_GATEWAY_TOKEN_FILE_DESCRIPTOR",
            "CLAUDE_CODE_HFI_BEARER_TOKEN",
            "CLAUDE_CODE_WEBSOCKET_AUTH_FILE_DESCRIPTOR",
            "CLAUDE_CODE_HOST_AUTH_ENV_VAR",
            "CLAUDE_CODE_HOST_CREDS_FILE",
            "CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST",
            "CLAUDE_CODE_REMOTE_TOOLS_PIN_STORED_LOGIN",
        ],
    )
    def test_strips_credential_supply_vars(self, tmp_path: Path, monkeypatch, var: str) -> None:
        # arrange — pre-seeded or host-managed auth material would bypass
        # or skew the interactive login
        monkeypatch.setenv(var, "must-not-leak")
        stub = make_stub(tmp_path, exit_code=0)
        launcher = ClaudeLoginLauncher(executable=str(stub))

        # act
        assert launcher.launch(tmp_path / "accounts" / "work") is True

        # assert
        called = json.loads((tmp_path / "called.json").read_text(encoding="utf-8"))
        assert var not in called

    @pytest.mark.parametrize(
        "var",
        [
            "ANTHROPIC_CONFIG_DIR",
            "ANTHROPIC_PROFILE",
            "CLAUDE_CODE_FEDERATION_CACHE_DIR",
        ],
    )
    def test_strips_wrong_slot_redirect_vars(self, tmp_path: Path, monkeypatch, var: str) -> None:
        # arrange — the federation store resolves through these; a login
        # under them would land outside .credentials.json entirely
        monkeypatch.setenv(var, "must-not-leak")
        stub = make_stub(tmp_path, exit_code=0)
        launcher = ClaudeLoginLauncher(executable=str(stub))

        # act
        assert launcher.launch(tmp_path / "accounts" / "work") is True

        # assert
        called = json.loads((tmp_path / "called.json").read_text(encoding="utf-8"))
        assert var not in called

    @pytest.mark.parametrize(
        "var",
        [
            "CLAUDE_CODE_USER_EMAIL",
            "CLAUDE_CODE_ORGANIZATION_UUID",
            "CLAUDE_CODE_SUBSCRIPTION_TYPE",
            "CLAUDE_CODE_RATE_LIMIT_TIER",
        ],
    )
    def test_strips_identity_injection_vars(self, tmp_path: Path, monkeypatch, var: str) -> None:
        # arrange — ambient identity claims would skew the captured
        # oauthAccount identity for the added account
        monkeypatch.setenv(var, "must-not-leak")
        stub = make_stub(tmp_path, exit_code=0)
        launcher = ClaudeLoginLauncher(executable=str(stub))

        # act
        assert launcher.launch(tmp_path / "accounts" / "work") is True

        # assert
        called = json.loads((tmp_path / "called.json").read_text(encoding="utf-8"))
        assert var not in called

    @pytest.mark.parametrize(
        "var",
        [
            "CLAUDE_ENV_FILE",
            "ANTHROPIC_CUSTOM_HEADERS",
        ],
    )
    def test_strips_indirect_injection_vars(self, tmp_path: Path, monkeypatch, var: str) -> None:
        # arrange — an env file re-imports everything stripped; injected
        # headers ride every login-exchange request
        monkeypatch.setenv(var, "must-not-leak")
        stub = make_stub(tmp_path, exit_code=0)
        launcher = ClaudeLoginLauncher(executable=str(stub))

        # act
        assert launcher.launch(tmp_path / "accounts" / "work") is True

        # assert
        called = json.loads((tmp_path / "called.json").read_text(encoding="utf-8"))
        assert var not in called

    def test_strips_the_original_credential_vars(self, tmp_path: Path, monkeypatch) -> None:
        # arrange — the pre-T6 credential vars still hold (regression pin)
        for var in (
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_AUTH_TOKEN",
            "CLAUDE_CODE_OAUTH_TOKEN",
            "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
            "CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR",
            "CLAUDE_SECURESTORAGE_CONFIG_DIR",
        ):
            monkeypatch.setenv(var, "must-not-leak")
        stub = make_stub(tmp_path, exit_code=0)
        launcher = ClaudeLoginLauncher(executable=str(stub))

        # act
        assert launcher.launch(tmp_path / "accounts" / "work") is True

        # assert
        called = json.loads((tmp_path / "called.json").read_text(encoding="utf-8"))
        for var in (
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_AUTH_TOKEN",
            "CLAUDE_CODE_OAUTH_TOKEN",
            "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
            "CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR",
            "CLAUDE_SECURESTORAGE_CONFIG_DIR",
        ):
            assert var not in called


class TestVersionGate:
    """launch resolves the shared claude contract before spawning — the
    credential write protocol cam interoperates with exists complete only
    from 2.1.144 and is unverified from 2.2.0. The login stub must never
    run on a refused contract."""

    def test_refuses_a_below_floor_claude(self, tmp_path: Path) -> None:
        # arrange — 0.2.x/1.x/2.0.x each lack part of the credential contract
        stub = make_stub(tmp_path, exit_code=0, version="0.2.126")
        launcher = ClaudeLoginLauncher(executable=str(stub))
        expected = (
            "claude 0.2.126 predates the credential contract cam "
            "interoperates with (introduced in 2.1.144) — upgrade claude"
        )

        # act / assert — the refusal names the detected version, verbatim
        with pytest.raises(UnsupportedClaudeVersionError, match=re.escape(expected)):
            launcher.launch(tmp_path / "accounts" / "work")
        # and the login itself never ran
        assert not (tmp_path / "called.json").exists()

    def test_refuses_a_claude_newer_than_the_verified_band(self, tmp_path: Path) -> None:
        # arrange — >=2.2.0 is unverified: fail closed with the override hint
        stub = make_stub(tmp_path, exit_code=0, version="2.2.0")
        launcher = ClaudeLoginLauncher(executable=str(stub))

        # act / assert
        with pytest.raises(
            UnsupportedClaudeVersionError,
            match=re.escape("claude 2.2.0 is newer than cam's verified contract"),
        ):
            launcher.launch(tmp_path / "accounts" / "work")
        assert not (tmp_path / "called.json").exists()

    def test_the_override_lets_a_newer_claude_launch(self, tmp_path: Path, monkeypatch) -> None:
        # arrange — the escape hatch for a claude newer than the verified band
        monkeypatch.setenv(CAM_ASSUME_CLAUDE_CONTRACT, "1")
        stub = make_stub(tmp_path, exit_code=0, version="2.2.0")
        launcher = ClaudeLoginLauncher(executable=str(stub))

        # act
        ok = launcher.launch(tmp_path / "accounts" / "work")

        # assert — override assumed the contract, so the login ran
        assert ok is True
        assert (tmp_path / "called.json").exists()

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
        expected = f"{stub} --version exited 3: 2.1.287 (Claude Code)"

        # act / assert
        with pytest.raises(ValueError, match=re.escape(expected)):
            launcher.launch(tmp_path / "accounts" / "work")
        assert not (tmp_path / "called.json").exists()

    def test_a_missing_executable_is_a_contract_refusal(self, tmp_path: Path) -> None:
        # arrange — no binary means no verifiable contract: refuse, don't
        # silently fall through to a launch that cannot succeed anyway
        launcher = ClaudeLoginLauncher(executable=str(tmp_path / "no-claude"))

        # act / assert
        with pytest.raises(
            UnsupportedClaudeVersionError, match="could not determine the claude version"
        ):
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

    def test_boundary_2_1_144_launches(self, tmp_path: Path) -> None:
        # arrange — 2.1.144 is the first release carrying the full credential
        # contract (wS() + .storage-write + .oauth_refresh.lock together)
        stub = make_stub(tmp_path, exit_code=0, version="2.1.144")
        launcher = ClaudeLoginLauncher(executable=str(stub))

        # act
        ok = launcher.launch(tmp_path / "accounts" / "work")

        # assert
        assert ok is True
        assert (tmp_path / "called.json").exists()
