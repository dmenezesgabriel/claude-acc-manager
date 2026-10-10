"""The release-notice wording — one render shared by every surface.

The post-command stderr notice prints it, the TUI mount toast shows it, and
``cam auto``'s ``update-available`` event line carries it — all three import
from here so the phrasing cannot drift (the ``switch_message`` precedent).
"""


def update_message(current_version: str, latest_version: str) -> str:
    """The notice line: a newer release exists; ``cam upgrade`` is the remedy.

    Example:
        ``update_message("1.0.0", "1.1.0")`` returns
        ``"cam 1.1.0 is available (you have 1.0.0) — run `cam upgrade`"``
    """
    return f"cam {latest_version} is available (you have {current_version}) — run `cam upgrade`"


def update_applying_message(current_version: str, latest_version: str) -> str:
    """The ``updates.mode=auto`` lead-in printed before the delegation runs.

    Example:
        ``update_applying_message("1.0.0", "1.0.1")`` returns
        ``"cam 1.0.1 is available (you have 1.0.0) — applying patch update"``
    """
    return f"cam {latest_version} is available (you have {current_version}) — applying patch update"
