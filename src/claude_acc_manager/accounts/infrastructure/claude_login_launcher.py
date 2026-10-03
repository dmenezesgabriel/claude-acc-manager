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

# The groups below are every hazard-class literal the 2.1.288 linux-x64
# binary reads (env sweep of package/claude — grep -oaE against the
# extracted native bundle). Verified, not guessed: keep additions
# evidence-pinned the same way.

# Endpoint redirects — an ambient base-URL or local-OAuth override would
# route the login's OAuth/API traffic away from Anthropic's hosts.
_ENDPOINT_REDIRECT_ENV_VARS = (
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
)

# Credential supply — pre-seeded or host-managed auth material would
# bypass or skew the interactive login.
_CREDENTIAL_SUPPLY_ENV_VARS = (
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
)

# Wrong-slot redirects — the verified band's claude resolves its credential
# store via CLAUDE_SECURESTORAGE_CONFIG_DIR (wS(), docs/adr/0015): any
# defined value — including "" which forces ~/.claude — overrides
# CLAUDE_CONFIG_DIR, so leaking it would land the login outside the account
# dir. The ANTHROPIC_* vars drive a separate federation store, a login that
# lands outside .credentials.json entirely.
_WRONG_SLOT_ENV_VARS = (
    "CLAUDE_SECURESTORAGE_CONFIG_DIR",
    "ANTHROPIC_CONFIG_DIR",
    "ANTHROPIC_PROFILE",
    "CLAUDE_CODE_FEDERATION_CACHE_DIR",
)

# Identity injection — ambient claims would skew the captured oauthAccount
# identity for the added account.
_IDENTITY_INJECTION_ENV_VARS = (
    "CLAUDE_CODE_USER_EMAIL",
    "CLAUDE_CODE_ORGANIZATION_UUID",
    "CLAUDE_CODE_SUBSCRIPTION_TYPE",
    "CLAUDE_CODE_RATE_LIMIT_TIER",
)

# Indirect/request injection — CLAUDE_ENV_FILE re-imports an arbitrary env
# set (re-arming everything above); ANTHROPIC_CUSTOM_HEADERS rides every
# login-exchange request.
_INDIRECT_INJECTION_ENV_VARS = (
    "CLAUDE_ENV_FILE",
    "ANTHROPIC_CUSTOM_HEADERS",
)

_STRIPPED_ENV_VARS = (
    _CREDENTIAL_ENV_VARS
    + _ENDPOINT_REDIRECT_ENV_VARS
    + _CREDENTIAL_SUPPLY_ENV_VARS
    + _WRONG_SLOT_ENV_VARS
    + _IDENTITY_INJECTION_ENV_VARS
    + _INDIRECT_INJECTION_ENV_VARS
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
