"""install_method — which package manager owns this cam, and from what source.

``cam upgrade`` delegates to the installer, so it must know which one put cam
here. The manager comes from ``sys.prefix``: uv tools live under
``…/uv/tools/<pkg>`` and pipx venvs under ``…/pipx/venvs/<pkg>``, or under a
relocated ``UV_TOOL_DIR`` / ``PIPX_HOME``. The receipt the manager wrote into
that prefix then says whether cam came from PyPI. A git or local install is
``VCS``: ``uv tool upgrade`` on a git receipt re-resolves the ref, not the
release, so a blind upgrade would not do what the user asked. A missing or
unreadable receipt is ``UNKNOWN`` for the same reason.

Example:
    method = detect_install_method(PurePath(sys.prefix), os.environ, receipt_text)
"""

import enum
import itertools
import json
import re
import tomllib
from collections.abc import Mapping
from pathlib import PurePath
from typing import cast

_DIST_NAME = "claude-acc-manager"
# Keys uv writes for a non-registry requirement source (uv's
# RequirementSourceWire); a registry entry carries only specifier/index.
_UV_SOURCE_KEYS = frozenset({"git", "url", "path", "directory", "editable", "virtual"})
# pipx stores a canonical PEP 508 string: the bare name, optionally with extras
# and a version specifier. ``name @ url``, a bare URL, or a resolved path are not.
_PIPX_REGISTRY_SPEC = re.compile(re.escape(_DIST_NAME) + r"(\[[^\]@]*\])?([<>=!~][^@]*)?")


class InstallMethod(enum.StrEnum):
    """Who installed cam; only UV and PIPX may be upgraded by delegation."""

    UV = "uv"
    PIPX = "pipx"
    VCS = "vcs"
    UNKNOWN = "unknown"


def detect_install_method(
    prefix: PurePath, env: Mapping[str, str], receipt: str | None
) -> InstallMethod:
    """Classify the install from its prefix and the manager's receipt text.

    Args:
        prefix: ``sys.prefix`` of the running interpreter.
        env: The process environment, for ``UV_TOOL_DIR`` / ``PIPX_HOME``.
        receipt: Text of ``<prefix>/uv-receipt.toml`` for uv or
            ``<prefix>/pipx_metadata.json`` for pipx; ``None`` if absent.

    Returns:
        UV or PIPX for a registry install, VCS for a git/local one, else UNKNOWN.

    Example:
        ``detect_install_method(PurePath("/h/.local/share/uv/tools/claude-acc-manager"), {}, text)``
    """
    manager = _manager_from_prefix(prefix, env)
    if manager is InstallMethod.UNKNOWN or receipt is None:
        return InstallMethod.UNKNOWN
    from_registry = (
        _uv_receipt_is_registry(receipt)
        if manager is InstallMethod.UV
        else _pipx_metadata_is_registry(receipt)
    )
    if from_registry is None:
        return InstallMethod.UNKNOWN
    return manager if from_registry else InstallMethod.VCS


def upgrade_argv(method: InstallMethod, target: str | None = None) -> list[str] | None:
    """The manager argv that upgrades cam, or None when delegation can't.

    uv accepts a ``name==version`` specifier on ``tool upgrade`` (verified
    against ``uv tool upgrade --help``, 2026-10-10); ``pipx upgrade`` takes
    the bare name only, so a pinned upgrade is not delegable under pipx —
    the transport prints the ``pipx install --force`` manual step instead.
    VCS and UNKNOWN never delegate: a git receipt re-resolves the ref, not
    the release, and an unreadable install may be a source checkout.

    Example:
        ``upgrade_argv(InstallMethod.UV, "1.2.0")`` returns
        ``["uv", "tool", "upgrade", "claude-acc-manager==1.2.0"]``
    """
    if method is InstallMethod.UV:
        spec = f"{_DIST_NAME}=={target}" if target is not None else _DIST_NAME
        return ["uv", "tool", "upgrade", spec]
    if method is InstallMethod.PIPX and target is None:
        return ["pipx", "upgrade", _DIST_NAME]
    return None


def _manager_from_prefix(prefix: PurePath, env: Mapping[str, str]) -> InstallMethod:
    pairs = set(itertools.pairwise(prefix.parts))
    if ("uv", "tools") in pairs:
        return InstallMethod.UV
    if ("pipx", "venvs") in pairs:
        return InstallMethod.PIPX
    for variable, manager in (("UV_TOOL_DIR", InstallMethod.UV), ("PIPX_HOME", InstallMethod.PIPX)):
        root = env.get(variable)
        # An empty root would make every relative prefix "under" it.
        if root and prefix.is_relative_to(root):
            return manager
    return InstallMethod.UNKNOWN


def _uv_receipt_is_registry(receipt: str) -> bool | None:
    try:
        document: object = tomllib.loads(receipt)
    except tomllib.TOMLDecodeError:
        return None
    requirements = _field(document, "tool", "requirements")
    if not isinstance(requirements, list):
        return None
    for requirement in cast("list[object]", requirements):  # pragma: no mutate — cast() is a no-op
        if _field(requirement, "name") != _DIST_NAME:
            continue
        table = cast("Mapping[str, object]", requirement)  # pragma: no mutate — a no-op
        return _UV_SOURCE_KEYS.isdisjoint(table)
    return None


def _pipx_metadata_is_registry(metadata: str) -> bool | None:
    try:
        document: object = json.loads(metadata)
    except json.JSONDecodeError:
        return None
    spec = _field(document, "main_package", "package_or_url")
    if not isinstance(spec, str):
        return None
    return _PIPX_REGISTRY_SPEC.fullmatch(spec) is not None


def _field(node: object, *keys: str) -> object:
    """Walk *keys* through nested tables; None where a level is not a table."""
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = cast("Mapping[str, object]", node).get(key)  # pragma: no mutate — cast() is a no-op
    return node
