"""Detect whether the process runs inside a container.

Evidence: claude-swap ``switcher.py`` ``_is_running_in_container`` — env vars
(``CONTAINER``/``container``), the ``/.dockerenv`` marker, container-runtime
names in ``/proc/1/cgroup``, and docker/overlay signatures in
``/proc/self/mountinfo``. The root guard (docs/architecture.md §8.6) consults
this: root on bare metal is refused, root inside a container is routine.

Example:
    running_in_container(os.environ, Path("/"))
"""

from collections.abc import Mapping
from pathlib import Path

_CGROUP_MARKERS = ("docker", "lxc", "containerd", "kubepods")
_MOUNTINFO_MARKERS = ("docker", "overlay")


def _file_mentions(path: Path, markers: tuple[str, ...]) -> bool:
    """True when *path* exists and its text contains any *markers* substring.

    An unreadable file is skipped, not fatal (claude-swap's PermissionError
    pass-through — a hardened host may hide /proc entries).
    """
    if not path.exists():
        return False
    try:
        # claude-swap reads these bare — the probed /proc files are
        # kernel-generated ASCII, so the locale default encoding is fine.
        content = path.read_text()
    except PermissionError:
        return False
    return any(marker in content for marker in markers)


def running_in_container(env: Mapping[str, str], fs_root: Path) -> bool:
    """True when the process looks container-hosted.

    Probes in claude-swap's order: ``CONTAINER``/``container`` env vars, the
    ``.dockerenv`` marker file, runtime names in ``proc/1/cgroup``, and
    docker/overlay mounts in ``proc/self/mountinfo``. *fs_root* anchors the
    absolute probe paths — ``Path("/")`` in production, a tmp tree in tests.

    Example:
        running_in_container({"container": "podman"}, Path("/")) is True
    """
    if env.get("CONTAINER") or env.get("container"):
        return True
    if (fs_root / ".dockerenv").exists():
        return True
    if _file_mentions(fs_root / "proc/1/cgroup", _CGROUP_MARKERS):
        return True
    return _file_mentions(fs_root / "proc/self/mountinfo", _MOUNTINFO_MARKERS)
