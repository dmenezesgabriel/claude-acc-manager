"""claude-acc-manager: manage, measure, and swap Claude Code OAuth accounts."""

from importlib.metadata import PackageNotFoundError, version


def package_version() -> str:
    """The installed dist version; ``0.0.0+local`` for an unpacked checkout.

    Example:
        ``cam --version`` prints ``f"cam {package_version()}"``.
    """
    try:
        # pragma: no mutate justification: PEP 503 normalizes dist names
        # case-insensitively, so mutmut's case mutation of the literal is an
        # equivalent mutant; the lookup is pinned end-to-end by
        # TestVersionFlag's dist-metadata assertion.
        return version("claude-acc-manager")  # pragma: no mutate
    except PackageNotFoundError:
        return "0.0.0+local"


__version__ = package_version()
