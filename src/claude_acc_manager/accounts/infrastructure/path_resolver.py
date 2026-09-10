"""Path resolution mirroring claude-code's own file layout.

Mirrors claude-code's resolution so this tool reads and writes the same files
claude-code does (claude-code `utils/env.ts getGlobalClaudeFile`,
`utils/secureStorage/plainTextStorage.ts`; verified in
research_repos/claude-swap/src/claude_swap/paths.py — the M0 empirical probe
still re-verifies this on the installed claude version).

Key rules:

- Config home: ``CLAUDE_CONFIG_DIR`` if set, else ``~/.claude``.
- Credentials: ``<config_home>/.credentials.json``.
- Global config: legacy ``<config_home>/.config.json`` if it exists, else
  ``(CLAUDE_CONFIG_DIR || $HOME)/.claude.json`` — note the asymmetry:
  ``.claude.json`` sits at homedir by default, not inside ``.claude/``.

All resolvers take the environment mapping and home directory as parameters,
never ambient state, so callers and tests can run fully hermetically.

Example:
    >>> home = Path("/home/user")
    >>> claude_config_home({}, home)
    PosixPath('/home/user/.claude')
"""

from collections.abc import Mapping
from pathlib import Path


def claude_config_home(env: Mapping[str, str], home: Path) -> Path:
    """Return the claude config home: CLAUDE_CONFIG_DIR or ~/.claude.

    Example:
        claude_config_home({"CLAUDE_CONFIG_DIR": "/tmp/a"}, Path("/h")) == Path("/tmp/a")
    """
    override = env.get("CLAUDE_CONFIG_DIR")
    if override:
        return Path(override)
    return home / ".claude"


def credentials_path(env: Mapping[str, str], home: Path) -> Path:
    """Return the OAuth credentials file: <config_home>/.credentials.json.

    Example:
        credentials_path({}, Path("/h")) == Path("/h/.claude/.credentials.json")
    """
    return claude_config_home(env, home) / ".credentials.json"


def global_config_path(env: Mapping[str, str], home: Path) -> Path:
    """Return the global config path (legacy fallback, homedir asymmetry).

    Example:
        global_config_path({}, Path("/h")) == Path("/h/.claude.json")
    """
    legacy = claude_config_home(env, home) / ".config.json"
    if legacy.exists():
        return legacy
    if env.get("CLAUDE_CONFIG_DIR"):
        return Path(env["CLAUDE_CONFIG_DIR"]) / ".claude.json"
    return home / ".claude.json"


def data_home(env: Mapping[str, str], home: Path) -> Path:
    """Return the XDG data home for this tool's store.

    Per the XDG Base Directory Specification: $XDG_DATA_HOME is used only when
    absolute (unset, empty and non-absolute values are ignored); a leading "~"
    is expanded against the caller's home (systemd units and containers don't
    get shell expansion).

    Example:
        data_home({}, Path("/h")) == Path("/h/.local/share")
    """
    # No default argument: unset must yield None (falsy) — identical behavior,
    # but avoids an unobservable literal that mutation testing rightly flags.
    xdg = env.get("XDG_DATA_HOME")
    if xdg:
        expanded = Path(xdg.replace("~", str(home), 1))
        if expanded.is_absolute():
            return expanded
    return home / ".local" / "share"
