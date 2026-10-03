"""Atomic private-mode file writes (the docs/architecture.md §8 single implementation).

mkstemp instead of write-then-chmod — the temp file carries live OAuth
refresh tokens, so it must be 0600 from creation, immune to the process umask
(ADR-0003). fsync of the temp file before the rename so a crash can never
publish a truncated credential file.

Example:
    atomic_write_json(Path("~/.local/share/cam/registry.json"), {"active": None})
"""

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path


def ensure_private_dir(path: Path) -> None:
    """Ensure *path* is a directory with mode 0700, creating it if missing.

    Missing ancestor levels are created 0700 too; an ancestor that already
    exists is left as-is, so a shared XDG parent keeps its mode (the chmod is
    unconditional only on levels we create or on *path* itself — tighten our
    own tree, never the shared anchor).

    Example:
        ensure_private_dir(Path.home() / ".local" / "share" / "claude-acc-manager")
    """
    if path.exists():
        os.chmod(path, 0o700)
        return
    if not path.parent.exists():
        ensure_private_dir(path.parent)
    path.mkdir(exist_ok=True)
    os.chmod(path, 0o700)


def _write_all(fd: int, data: bytes) -> None:
    """Write every byte of *data*: os.write may accept fewer bytes than given."""
    written = 0
    while written < len(data):
        # pragma: no mutate — the += mutant spins an unbounded write loop
        # (written goes negative, slice start collapses to 0) that only ends
        # at disk-fill OSError or mutmut's CPU-limit kill; no finite test
        # outcome can tell the mutant apart from the real loop.
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


def read_json_object(path: Path, label: str) -> dict[str, object]:
    """Parse *path* as a JSON object; raise ValueError when torn or not one.

    The docs/architecture.md §8 rule "tears surface, not swallowed": a file that exists but
    cannot be parsed must never be silently treated as absent.

    Example:
        read_json_object(Path("/h/.claude.json"), "config")
    """
    try:
        data = json.loads(path.read_bytes())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"{label} file {path} is torn — could not be parsed: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{label} file {path} is {type(data).__name__}, not a JSON object")
    return data  # type: ignore[return-value]
