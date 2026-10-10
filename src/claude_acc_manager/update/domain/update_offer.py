"""UpdateOffer — what CheckUpdate returns when PyPI has a newer release.

The surfaces (stderr notice, TUI toast, auto event line) render it; the
``auto`` mode reads ``release_type`` to decide whether the offer may
self-apply — only PATCH may (opencode's rule, adopted).

Example:
    offer = UpdateOffer(
        current_version="1.1.0", latest_version="1.2.0", release_type=ReleaseType.MINOR
    )
"""

from dataclasses import dataclass

from claude_acc_manager.update.domain.services.version_order import ReleaseType


@dataclass(frozen=True)
class UpdateOffer:
    """A strictly-newer final release exists on the index.

    ``current_version`` is always a parsed final release (a dev checkout
    never produces an offer); ``latest_version`` is what the index reported,
    guaranteed newer by ``is_newer``.
    """

    current_version: str
    latest_version: str
    release_type: ReleaseType
