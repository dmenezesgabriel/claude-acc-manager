"""Stand-in for the ``claude_acc_manager.tui`` package's ``run`` entry point.

Inserted into ``sys.modules`` under the package name so ``cmd_tui``'s lazy
``from claude_acc_manager.tui import run`` resolves to the recorder — no
textual import, no real terminal, and the recorded ``start`` screen is the
assertion seam.
"""

from claude_acc_manager.cli.context import UseCases


class FakeTuiModule:
    """Records the ``start`` screen each ``run`` asks for."""

    def __init__(self, exit_code: int = 0) -> None:
        """Pin the code ``run`` reports back to the dispatcher."""
        self._exit_code = exit_code
        self.starts: list[str] = []

    def run(self, use_cases: UseCases, *, start: str = "dashboard") -> int:
        """Record *start*; return the pinned exit code."""
        self.starts.append(start)
        return self._exit_code
