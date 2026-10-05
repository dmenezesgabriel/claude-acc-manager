"""OS-backed ``DiagnosticsPort`` — every ambient read ``cam doctor`` shows.

env / home / store_root are injected so tests stay hermetic; the claude
contract verdict comes through the same injected port the mutating paths
use. Lock states reuse the swap path's own staleness constants — a lock
older than its bound is a dead holder's artifact, reported as such.
"""

import fcntl
import os
import platform
import sys
import time
from collections.abc import Mapping
from pathlib import Path

from claude_acc_manager.accounts.application.doctor_report import (
    DiagnosticsFacts,
    LockObservation,
)
from claude_acc_manager.accounts.application.ports import (
    ClaudeContractPort,
    DiagnosticsPort,
)
from claude_acc_manager.accounts.infrastructure.claude_locks import (
    CONFIG_STALENESS_S,
    CREDENTIALS_STALENESS_S,
    STORAGE_WRITE_STALENESS_S,
)
from claude_acc_manager.accounts.infrastructure.path_resolver import (
    config_lock_dir,
    credentials_lock_dir,
    credentials_path,
    global_config_path,
    oauth_refresh_lock_dir,
    secure_storage_home,
)
from claude_acc_manager.shared.container import running_in_container

_OPS_LOCK_NAME = ".ops.lock"


def _mkdir_lock(name: str, path: Path, staleness_s: float) -> LockObservation:
    """One mkdir lock's state: absent, held, or stale past *staleness_s*."""
    try:
        age_s = time.time() - path.stat().st_mtime
    except OSError:
        return LockObservation(name, path, "free", None)
    state = "stale" if age_s > staleness_s else "held"
    return LockObservation(name, path, state, age_s)


def _flock_observation(name: str, path: Path) -> LockObservation:
    """An flock file's state: free unless another process holds it."""
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT)
    except OSError:
        # Missing store (or unwritable path): no observable holder.
        return LockObservation(name, path, "free", None)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return LockObservation(name, path, "free", None)
        except OSError:
            return LockObservation(name, path, "held", None)
    finally:
        os.close(fd)


class OsDiagnosticsProbe(DiagnosticsPort):
    """Probe the real process, filesystem, and claude binary.

    Example:
        facts = OsDiagnosticsProbe(
            env=os.environ, home=Path.home(),
            store_root=Path("~/.local/share/claude-acc-manager"),
            contract_probe=SubprocessClaudeContractProbe(),
            fs_root=Path("/"),
        ).probe()
    """

    def __init__(
        self,
        *,
        env: Mapping[str, str],
        home: Path,
        store_root: Path,
        contract_probe: ClaudeContractPort,
        fs_root: Path,
    ) -> None:
        """Pin the ambient inputs — nothing else is read at construction."""
        self._env = env
        self._home = home
        self._store_root = store_root
        self._contract_probe = contract_probe
        self._fs_root = fs_root

    def probe(self) -> DiagnosticsFacts:
        """Take one snapshot of every fact the report renders."""
        creds_path = credentials_path(self._env, self._home)
        config_path = global_config_path(self._env, self._home)
        stdin_tty = sys.stdin.isatty()
        stdout_tty = sys.stdout.isatty()
        return DiagnosticsFacts(
            contract=self._contract_probe.probe(),
            store_root=self._store_root,
            store_exists=self._store_root.is_dir(),
            accounts_dir=self._store_root / "accounts",
            accounts_dir_exists=(self._store_root / "accounts").is_dir(),
            credentials_path=creds_path,
            credentials_present=creds_path.is_file(),
            config_path=config_path,
            config_present=config_path.is_file(),
            locks=self._lock_states(),
            env=self._env,
            stdin_tty=stdin_tty,
            stdout_tty=stdout_tty,
            interactive=(
                stdin_tty and stdout_tty and self._env.get("TERM") not in ("dumb", "unknown")
            ),
            euid=os.geteuid(),
            in_container=running_in_container(self._env, self._fs_root),
            python=f"{platform.python_implementation()} {platform.python_version()}",
            platform=platform.platform(),
        )

    def _lock_states(self) -> tuple[LockObservation, ...]:
        """Claude's mkdir locks plus cam's own flock."""
        storage = secure_storage_home(self._env, self._home)
        return (
            _mkdir_lock(
                "oauth refresh",
                oauth_refresh_lock_dir(self._env, self._home),
                CREDENTIALS_STALENESS_S,
            ),
            _mkdir_lock(
                "credentials", credentials_lock_dir(self._env, self._home), CREDENTIALS_STALENESS_S
            ),
            _mkdir_lock("config", config_lock_dir(self._env, self._home), CONFIG_STALENESS_S),
            _mkdir_lock("storage write", storage / ".storage-write", STORAGE_WRITE_STALENESS_S),
            _flock_observation("cam ops", self._store_root / _OPS_LOCK_NAME),
        )
