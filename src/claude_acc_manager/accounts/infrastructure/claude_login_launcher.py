"""Adapter that launches an isolated claude login (ADR-0009).

Sets ``CLAUDE_CONFIG_DIR`` to the account's own dir, strips ambient
credential env vars, and blocks until exit. The login lands directly in the
account's own config dir — tokens are never copied at add time. Before
spawning, the shared claude contract must hold: the credential write
protocol cam interoperates with exists complete only from claude 2.1.144
and is unverified from 2.2.0 (shared/claude_contract.py carries the band).

Example:
    launcher = ClaudeLoginLauncher()
    ok = launcher.launch(Path("~/.local/share/cam/accounts/work"))
"""

import os
import subprocess
from pathlib import Path

from claude_acc_manager.accounts.application.ports import LoginLauncherPort
from claude_acc_manager.shared.claude_contract import probe_claude_contract

# Ambient credentials would short-circuit claude's OAuth login prompt,
# stranding the account's own login in the isolated dir.
_CREDENTIAL_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
    "CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR",
)

# claude 2.1.x resolves its credential store via CLAUDE_SECURESTORAGE_CONFIG_DIR
# (wS()): any defined value — including "" which forces ~/.claude — overrides
# CLAUDE_CONFIG_DIR, so leaking it would land the login outside the account dir.
_PATH_REDIRECT_ENV_VARS = ("CLAUDE_SECURESTORAGE_CONFIG_DIR",)

_STRIPPED_ENV_VARS = _CREDENTIAL_ENV_VARS + _PATH_REDIRECT_ENV_VARS


class ClaudeLoginLauncher(LoginLauncherPort):
    """Run ``claude`` with CLAUDE_CONFIG_DIR scoped to one account dir.

    Example:
        ok = ClaudeLoginLauncher().launch(Path("/tmp/account-dir"))
    """

    def __init__(self, executable: str = "claude") -> None:
        """Name the binary on PATH (injectable for hermetic stub-binary tests)."""
        self._executable = executable

    def launch(self, account_dir: Path) -> bool:
        """Exit 0 = login completed; missing binary or non-zero = failure.

        Inherits stdout/stderr so the interactive login runs in the terminal;
        only the returned bool crosses the boundary. Raises
        UnsupportedClaudeVersionError when the installed claude is outside
        cam's verified contract band — an unverified login must not write
        credentials under a contract cam does not know how to interoperate
        with. The probe interrogates this same executable: the version that
        is verified is the binary that is launched.
        """
        contract = probe_claude_contract(os.environ, self._executable)
        contract.require_supported()
        env = {k: v for k, v in os.environ.items() if k not in _STRIPPED_ENV_VARS}
        env["CLAUDE_CONFIG_DIR"] = str(account_dir)
        try:
            result = subprocess.run([self._executable], env=env)
        except OSError:
            return False
        return result.returncode == 0
