"""Path resolution mirroring claude-code's own file layout.

Mirrors claude-code's resolution so this tool reads and writes the same files
claude-code does (claude-code `utils/env.ts getGlobalClaudeFile`,
`utils/secureStorage/plainTextStorage.ts`; a scoped-login probe against the
installed claude version still re-verifies this).

Key rules:

- Config home: ``CLAUDE_CONFIG_DIR`` if set, else ``~/.claude``.
- Secure-storage home (``wS()``, verified on claude [2.1.144, 2.2.0) —
  docs/adr/0015): ``CLAUDE_SECURESTORAGE_CONFIG_DIR`` whenever defined — a
  defined-but-empty value means ``~/.claude`` — else the config home.
  ``.credentials.json`` and claude's credential locks live here.
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


def secure_storage_home(env: Mapping[str, str], home: Path) -> Path:
    """Return the secure-storage dir claude uses — where .credentials.json lives.

    Mirrors ``wS()`` in the claude bundle: a defined
    ``CLAUDE_SECURESTORAGE_CONFIG_DIR`` wins verbatim, except that a
    defined-but-empty value resolves to ``~/.claude``; when it is unset the
    ``CLAUDE_CONFIG_DIR`` chain (the config home) applies.

    Example:
        secure_storage_home({"CLAUDE_SECURESTORAGE_CONFIG_DIR": "/s"}, Path("/h"))
            == Path("/s")
    """
    override = env.get("CLAUDE_SECURESTORAGE_CONFIG_DIR")
    if override is not None:
        return Path(override) if override else home / ".claude"
    return claude_config_home(env, home)


def credentials_path(env: Mapping[str, str], home: Path) -> Path:
    """Return the OAuth credentials file: <secure_storage_home>/.credentials.json.

    Example:
        credentials_path({}, Path("/h")) == Path("/h/.claude/.credentials.json")
    """
    return secure_storage_home(env, home) / ".credentials.json"


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


def global_config_in(config_home: Path) -> Path:
    """Return the global config path for an explicit claude config home.

    Same rule as global_config_path's CLAUDE_CONFIG_DIR branch, stated for a
    config home that is already known (a per-account dir): legacy
    ``.config.json`` first, else ``.claude.json`` — both inside the home.

    Example:
        global_config_in(Path("/tmp/acc")) == Path("/tmp/acc/.claude.json")
    """
    legacy = config_home / ".config.json"
    if legacy.exists():
        return legacy
    return config_home / ".claude.json"


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


def _sibling_lock(next_to: Path) -> Path:
    """Return the mkdir lock path claude-code keeps beside *next_to*.

    Claude-code's mkdir locks sit next to the file or dir they guard
    (``<target>.lock``): ``~/.claude.json.lock`` guards ``~/.claude.json``,
    ``~/.claude.lock`` guards the ``~/.claude`` config home.
    """
    return Path(f"{next_to}.lock")


def oauth_refresh_lock_dir(env: Mapping[str, str], home: Path) -> Path:
    """Return the primary credential lock: <secure_storage_home>/.oauth_refresh.lock.

    Example:
        oauth_refresh_lock_dir({}, Path("/h")) == Path("/h/.claude/.oauth_refresh.lock")
    """
    return secure_storage_home(env, home) / ".oauth_refresh.lock"


def credentials_lock_dir(env: Mapping[str, str], home: Path) -> Path:
    """Return the legacy credential lock: realpath(<secure_storage_home>).lock.

    Upstream realpaths the storage dir before suffixing (``Xk``/``eH`` in the
    bundle): a symlinked ``~/.claude`` shares the lock at its target, not the
    link, so both processes contend on the same artifact.

    Example:
        credentials_lock_dir({}, Path("/h")) == Path("/h/.claude.lock")
    """
    return _sibling_lock(secure_storage_home(env, home).resolve())


def config_lock_dir(env: Mapping[str, str], home: Path) -> Path:
    """Return the config lock: the configured global-config path + ".lock".

    Follows every wrinkle of global_config_path, including the legacy
    ``<config_home>/.config.json`` reroute.

    Example:
        config_lock_dir({}, Path("/h")) == Path("/h/.claude.json.lock")
    """
    return _sibling_lock(global_config_path(env, home))
