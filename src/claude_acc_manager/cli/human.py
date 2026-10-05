"""Human-facing CLI output — one Rich-backed, markup-free sink.

Every human print in ``cli/`` goes through :class:`HumanOutput` so styling
degrades identically everywhere — ``NO_COLOR``, a non-TTY stdout, and
``TERM=dumb`` are all handled by ``rich.Console`` natively — and untrusted
text (account names, emails, provider error strings) is never parsed for
``[markup]`` or emoji codes. ``--json`` never touches this module: payloads
stay on the builtin ``print`` in ``dispatch``.

Example:
    out = HumanOutput()
    out.print(f"added account {name!r}")
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from claude_acc_manager.shared.palette import CRIT_PCT, WARN_PCT

if TYPE_CHECKING:
    from rich.console import Console
    from rich.text import Text

# Whole-line style per auto-event kind (SL-014): green for movement, red for
# hard outcomes, yellow for quarantine, dim for routine no-ops. Poll lines
# are plain — their used-pct carries the severity ramp instead.
_EVENT_STYLES: dict[str, str] = {
    "switch": "green",
    "error": "red",
    "all-exhausted": "red",
    "account-quarantined": "yellow",
    "sleep": "dim",
    "no-switch": "dim",
}


class HumanOutput:
    r"""Lazy consoles behind a markup-free, line-flushed print.

    The ``Console`` is built on first use so ``--json`` invocations never pay
    the rich import. A ``str`` is treated as final bytes — written verbatim,
    flush included — so pinned output (literal ``\t``, ``[`` ``]`` text)
    survives untouched; only ``Text`` renderables take the render path, and
    there only ``soft_wrap`` applies — spans they carry are their own.
    """

    def __init__(self, console: Console | None = None, err_console: Console | None = None) -> None:
        """Inject consoles (tests) or let them be built on first write."""
        self._console = console
        self._err_console = err_console

    def print(self, line: str | Text) -> None:
        """Write *line* to stdout; ``str`` is verbatim, ``Text`` is styled."""
        self._write(self._stdout(), line)

    def error(self, line: str | Text) -> None:
        """Write *line* to stderr — same verbatim/styled split."""
        self._write(self._stderr(), line)

    def severity_style(self, pct: float | None) -> str:
        """The utilization ramp as named ANSI styles — terminal-theme adaptive.

        Shares the WARN/CRIT edges with the TUI bar (``shared/palette.py``);
        unknown usage reads dim rather than alarming.

        Example:
            out.severity_style(95.0)  # "red"
        """
        if pct is None:
            return "dim"
        if pct >= CRIT_PCT:
            return "red"
        if pct >= WARN_PCT:
            return "yellow"
        return "green"

    def event_style(self, kind: str) -> str | None:
        """Whole-line style for an auto-event ``kind``; ``None`` = unstyled.

        Example:
            out.event_style("switch")  # "green"
        """
        return _EVENT_STYLES.get(kind)

    @staticmethod
    def _write(console: Console, line: str | Text) -> None:
        r"""Send *line* down *console* — ``str`` bypasses rendering entirely.

        ``Console.print`` always expands ``\t``; the plain-string fast path
        keeps the pinned interface byte-exact. ``Text`` carries its own
        spans, so markup/highlight/emoji (``render_str``-path transforms)
        can't touch it — ``soft_wrap`` is the only live flag, pinning long
        lines unfolded regardless of the injected console's width.
        """
        if isinstance(line, str):
            console.file.write(line + "\n")
            console.file.flush()
            return
        console.print(line, soft_wrap=True)

    def _stdout(self) -> Console:
        """The stdout console, built on first write (keeps --json paths lean)."""
        if self._console is None:
            from rich.console import Console

            self._console = Console()
        return self._console

    def _stderr(self) -> Console:
        """The stderr console — same literal-rendering flags."""
        if self._err_console is None:
            from rich.console import Console

            self._err_console = Console(stderr=True)
        return self._err_console
