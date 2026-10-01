"""Adapter that launches an isolated claude login (ADR-0009).

Evidence: ai-usagebar account.rs login_claude_account (sets CLAUDE_CONFIG_DIR,
strips ambient credential vars, blocks until exit) and claude-swap session.py
AUTH_OVERRIDE_ENV_VARS. The login lands directly in the account's own config
dir — tokens are never copied at add time.

Example:
    launcher = ClaudeLoginLauncher()
    ok = launcher.launch(Path("~/.local/share/cam/accounts/work"))
"""

import os
import subprocess
from pathlib import Path

from claude_acc_manager.accounts.application.ports import LoginLauncherPort

# claude-swap session.py:192-198 — ambient credentials would short-circuit
# claude's OAuth login prompt, stranding the account's own login in the
# isolated dir (ai-usagebar strips the same class of vars, account.rs:987).
_CREDENTIAL_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
    "CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR",
)


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
        only the returned bool crosses the boundary.
        """
        env = {k: v for k, v in os.environ.items() if k not in _CREDENTIAL_ENV_VARS}
        env["CLAUDE_CONFIG_DIR"] = str(account_dir)
        try:
            result = subprocess.run([self._executable], env=env)
        except OSError:
            return False
        return result.returncode == 0
