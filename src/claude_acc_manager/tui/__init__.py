"""Textual-based interactive TUI for cam.

Entry point for ``cam tui`` / ``cam watch``. Heavy imports (textual, rich)
stay inside :func:`run` so the plain CLI paths — ``cam list --json``, cron —
never pay for them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from claude_acc_manager.tui.app import TuiUseCases


def run(use_cases: TuiUseCases, *, start: str = "dashboard") -> int:
    """Run the TUI over the wired use cases; returns the process exit code.

    ``start="watch"`` (the ``cam watch`` command) opens directly on the live
    watch page, stacked over the dashboard so Esc lands there.

    Example:
        code = run(use_cases, start="watch")
    """
    from claude_acc_manager.tui.app import CamApp

    app = CamApp(use_cases, start=start)
    app.run()
    return app.return_code or 0
