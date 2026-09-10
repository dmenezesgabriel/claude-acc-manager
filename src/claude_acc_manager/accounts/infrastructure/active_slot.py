"""Adapter implementing ActiveSlotPort over Claude Code's live credential slot.

Evidence: claude-swap paths.py, credentials.py; ai-usagebar creds.rs,
cli_account.rs. The active slot is the default CLAUDE_CONFIG_DIR that plain
``claude`` reads from: ``~/.claude/.credentials.json`` for OAuth tokens and
``~/.claude.json`` for the ``oauthAccount`` identity marker.

Example:
    slot = ActiveSlotAdapter(env=os.environ, home=Path.home())
    creds = slot.read_credentials()
"""

import json
import os
from collections.abc import Mapping
from pathlib import Path

from claude_acc_manager.accounts.infrastructure.path_resolver import (
    credentials_path,
    global_config_path,
)
from claude_acc_manager.shared import fsio


class ActiveSlotAdapter:
    """ActiveSlotPort over Claude Code's live credential + config files.

    All paths are derived from injected *env* and *home* so tests run fully
    hermetically — nothing reads ambient state.

    Example:
        slot = ActiveSlotAdapter(env={}, home=Path("/tmp/hermetic-home"))
        creds = slot.read_credentials()
    """

    def __init__(self, env: Mapping[str, str], home: Path) -> None:
        """Store *env* and *home*: resolve Claude's slot paths from them."""
        self._env = env
        self._home = home

    def read_credentials(self) -> dict[str, object] | None:
        """Parse ``.credentials.json``; ``None`` when absent.

        Raises ValueError when the file exists but is torn or not a JSON object
        (plan §5.3: tears surface, not swallowed).
        """
        path = credentials_path(self._env, self._home)
        if not path.exists():
            return None
        return self._read_json_or_raise(path, "credentials")

    def write_credentials(self, credentials: dict[str, object]) -> None:
        """Atomically replace ``.credentials.json`` with mode 0600."""
        path = credentials_path(self._env, self._home)
        fsio.atomic_write_json(path, credentials)

    def read_config(self) -> dict[str, object] | None:
        """Parse ``~/.claude.json``; ``None`` when absent.

        Raises ValueError when the file exists but is torn or not a JSON object.
        """
        path = global_config_path(self._env, self._home)
        if not path.exists():
            return None
        return self._read_json_or_raise(path, "config")

    def write_config(self, config: dict[str, object]) -> None:
        """Atomically replace ``~/.claude.json`` with mode 0600."""
        path = global_config_path(self._env, self._home)
        fsio.atomic_write_json(path, config)

    def splice_config_oauth_account(self, oauth_account: dict[str, object]) -> None:
        """Read config → set only ``oauthAccount`` key → write back.

        When the config is torn, salvages it aside first then writes a fresh
        config containing only the ``oauthAccount`` key. Salvage failure aborts
        before overwrite (switcher.py:544-547: "aborting rather than destroying
        it").
        """
        path = global_config_path(self._env, self._home)
        existing = self._read_json_tolerant(path)
        if existing is not None:
            existing["oauthAccount"] = oauth_account
            self.write_config(existing)
        else:
            if path.exists():
                self.salvage_torn_config()
            self.write_config({"oauthAccount": oauth_account})

    def salvage_torn_config(self) -> Path | None:
        """Copy a torn config aside before it is overwritten.

        Naming: ``{name}.unreadable-{epoch}`` with ``.1``, ``.2``, … collision
        suffixes (switcher.py:533-538). Mode 0600 (switcher.py:541-542).

        Returns the salvage path, or ``None`` when the file is absent.
        Raises OSError when the salvage copy fails.
        """
        import shutil
        import time

        path = global_config_path(self._env, self._home)
        if not path.exists():
            return None
        stem = f"{path.name}.unreadable-{int(time.time())}"
        salvage = path.with_name(stem)
        n = 1
        while salvage.exists():
            salvage = path.with_name(f"{stem}.{n}")
            # pragma: no mutate justification: claude-swap switcher.py:533-538
            # uses this same while/`n += 1` loop. Mutating to `n = 1` makes the
            # loop unterminated once any `.1` collision exists, and mutmut 3.7
            # has no per-mutant timeout — the mutant cannot be killed, only
            # hung. The `.1`, `.2`, … suffix behavior is pinned by
            # test_collision_increments_counter_for_two_existing_salvages.
            n += 1  # pragma: no mutate
        shutil.copy(path, salvage)
        os.chmod(str(salvage), 0o600)
        return salvage

    def _read_json_or_raise(self, path: Path, label: str) -> dict[str, object]:
        """Read and parse a JSON file; raise on tear or non-object."""
        try:
            data = json.loads(path.read_bytes())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f"{label} file {path} is torn — could not be parsed: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"{label} file {path} is {type(data).__name__}, not a JSON object")
        return data  # type: ignore[return-value]

    def _read_json_tolerant(self, path: Path) -> dict[str, object] | None:
        """Read JSON; return ``None`` for absent OR unreadable (non-strict).

        The splice logic uses this to disambiguate via ``path.exists()``
        afterward — matching switcher.py:444-497 non-strict mode.
        """
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_bytes())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None  # type: ignore[return-value]
