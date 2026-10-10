"""version_order — is PyPI's release newer than ours, and by how much.

Hand-rolled because ADR-0002 keeps cam stdlib-only (no ``packaging``, no
``semver``). Only final releases (``N.N[.N…]``) take part: PEP 440 pre,
dev, post, and local versions parse to ``None``, so a prerelease is never
offered and a dev checkout (``0.0.0+local``, see ``package_version()``)
never asks. A missing component counts as zero, so ``1.1`` equals ``1.1.0``.

Example:
    if is_newer("1.1.0", "1.2.0"):
        bump = release_type("1.1.0", "1.2.0")  # ReleaseType.MINOR
"""

import enum
import itertools
import re

# ASCII digits only: ``\\d`` would admit Unicode digits that ``int()`` accepts.
_RELEASE = re.compile(r"[0-9]+(?:\.[0-9]+)+")


class ReleaseType(enum.StrEnum):
    """How big a jump an update is; ``updates.mode auto`` applies only PATCH."""

    PATCH = "patch"
    MINOR = "minor"
    MAJOR = "major"


def parse_release(text: str) -> tuple[int, ...] | None:
    """Parse a final release version into its integer components.

    Args:
        text: A version string such as PyPI's ``info.version``.

    Returns:
        The component tuple, or ``None`` for anything but a final release.

    Example:
        ``parse_release("1.10.0") == (1, 10, 0)``; ``parse_release("1.2.0rc1") is None``
    """
    # fullmatch, not match + "$": "$" would accept a trailing newline.
    if _RELEASE.fullmatch(text) is None:
        return None
    return tuple(int(part) for part in text.split("."))


def is_newer(current: str, candidate: str) -> bool:
    """Whether *candidate* is a strictly newer final release than *current*.

    A side that is not a final release yields ``False``: an update we
    cannot reason about is not one to offer.

    Example:
        ``is_newer("1.9.0", "1.10.0") is True``
    """
    ours, theirs = parse_release(current), parse_release(candidate)
    if ours is None or theirs is None:
        return False
    # Two strict compares rather than ``!=`` then ``>``: each operator then
    # decides an outcome on its own, so neither can be weakened unnoticed.
    for mine, yours in itertools.zip_longest(ours, theirs, fillvalue=0):
        if yours > mine:
            return True
        if yours < mine:
            return False
    return False


def release_type(current: str, latest: str) -> ReleaseType:
    """Classify the jump from *current* to *latest* by its first changed part.

    A major component change is MAJOR, a minor change is MINOR, and
    anything deeper is PATCH. This is opencode's ``getReleaseType`` rule.

    Raises:
        ValueError: If either side is not a final ``N.N[.N…]`` release.

    Example:
        ``release_type("1.1.0", "1.1.1") is ReleaseType.PATCH``
    """
    # No padding needed: parse_release guarantees at least two components.
    ours, theirs = _require_release(current), _require_release(latest)
    if theirs[0] != ours[0]:
        return ReleaseType.MAJOR
    if theirs[1] != ours[1]:
        return ReleaseType.MINOR
    return ReleaseType.PATCH


def _require_release(text: str) -> tuple[int, ...]:
    parsed = parse_release(text)
    if parsed is None:
        raise ValueError(f"version {text!r} is not a final release; expected 'N.N[.N…]'")
    return parsed
