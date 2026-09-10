"""Atomic private-mode file writes (the plan §5.3 single implementation).

Evidence for the pattern: claude-swap settings.py atomic_write_json and
transfer.py (mkstemp instead of write-then-chmod — the temp file carries live
OAuth refresh tokens, so it must be 0600 from creation, immune to the process
umask), ai-usagebar cache.rs atomic_write (fsync of the temp file before the
rename so a crash can never publish a truncated credential file).

Example:
    atomic_write_json(Path("~/.local/share/cam/registry.json"), {"active": None})
"""

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path


def ensure_private_dir(path: Path) -> None:
    """Create *path* with mode 0700 (and every new level below the anchor).

    The chmod is unconditional (claude-swap switcher.py _setup_directories);
    the anchor above our own tree is never touched, so shared XDG parents keep
    their mode.

    Example:
        ensure_private_dir(Path.home() / ".local" / "share" / "claude-acc-manager")
    """
    if path.exists():
        os.chmod(path, 0o700)
        return
    ensure_private_dir(path.parent)
    path.mkdir(exist_ok=True)
    os.chmod(path, 0o700)


def _write_all(fd: int, data: bytes) -> None:
    """Write every byte of *data*: os.write may accept fewer bytes than given."""
    written = 0
    while written < len(data):
        written += os.write(fd, data[written:])


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write *data* to *path* atomically with mode 0600.

    mkstemp in the target's directory (same filesystem → atomic rename, 0600
    from creation regardless of umask), fsync, then os.replace — the rename is
    the commit point, so a crash never publishes partial or truncated content.
    Any failure before publication removes the temp file and leaves the
    previous content of *path* untouched.

    Example:
        atomic_write_bytes(Path("registry.json"), b'{"schemaVersion": 1}')
    """
    ensure_private_dir(path.parent)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        try:
            _write_all(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    """Serialize *payload* as JSON and write it via atomic_write_bytes.

    Example:
        atomic_write_json(Path("registry.json"), {"accounts": {}})
    """
    payload_text = json.dumps(payload, indent=2)
    # pragma: no mutate justification: "UTF-8" is a case-insensitive codec
    # alias of "utf-8" — no test can distinguish them, mutants are equivalent.
    atomic_write_bytes(path, payload_text.encode("utf-8"))  # pragma: no mutate
