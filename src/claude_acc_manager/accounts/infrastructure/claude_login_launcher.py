"""Adapter that launches an isolated claude login (ADR-0009).

Sets ``CLAUDE_CONFIG_DIR`` to the account's own dir, strips ambient
credential env vars, and blocks until exit. The login lands directly in the
account's own config dir — tokens are never copied at add time.

Example:
    launcher = ClaudeLoginLauncher()
    ok = launcher.launch(Path("~/.local/share/cam/accounts/work"))
"""

import os
import re
import subprocess
from pathlib import Path

from claude_acc_manager.accounts.application.ports import LoginLauncherPort

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

# Before 1.0 the credential path is hardcoded ~/.claude/.credentials.json —
# CLAUDE_CONFIG_DIR cannot isolate the login (npm cli.js 0.2.126, NR1).
MIN_SUPPORTED_VERSION = (1, 0, 0)
_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")
_VERSION_PROBE_TIMEOUT_S = 15.0


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
        only the returned bool crosses the boundary. Raises ValueError when
        the installed claude predates 1.0 — it cannot isolate credentials —
        or when its version cannot be determined.
        """
        version = self._probe_version()
        if version is None:
            return False
        if version < MIN_SUPPORTED_VERSION:
            raise ValueError(
                f"claude {'.'.join(map(str, version))} cannot isolate a login: "
                "before 1.0 it ignores CLAUDE_CONFIG_DIR for .credentials.json, "
                "so the login would write the live slot — cam add requires "
                "claude >= 1.0"
            )
        env = {k: v for k, v in os.environ.items() if k not in _STRIPPED_ENV_VARS}
        env["CLAUDE_CONFIG_DIR"] = str(account_dir)
        try:
            result = subprocess.run([self._executable], env=env)
        except OSError:
            return False
        return result.returncode == 0

    def _probe_version(self) -> tuple[int, int, int] | None:
        """`claude --version` → semver tuple; None when the binary can't run.

        Raises ValueError when the probe exits non-zero or its output holds
        no semver — an undeterminable version must fail closed, not launch.
        """
        try:
            result = subprocess.run(
                [self._executable, "--version"],
                capture_output=True,
                text=True,
                timeout=_VERSION_PROBE_TIMEOUT_S,
            )
        except OSError:
            return None
        except subprocess.TimeoutExpired:
            raise ValueError(
                f"claude --version did not answer within {_VERSION_PROBE_TIMEOUT_S}s"
            ) from None
        if result.returncode != 0:
            raise ValueError(
                f"claude --version exited {result.returncode}: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        match = _VERSION_RE.search(result.stdout)
        if match is None:
            raise ValueError(
                f"could not parse claude version from {result.stdout!r} — "
                f"expected 'X.Y.Z (Claude Code)'"
            )
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)))
