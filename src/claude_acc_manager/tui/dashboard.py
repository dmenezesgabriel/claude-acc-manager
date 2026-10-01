"""Dashboard and watch screens.

The dashboard pairs the always-visible accounts monitor with a nested
action menu; the watch screen is the same monitor read-only. The menu and
the rest of the actions arrive with the remaining slices — the app-level
poll loop keeps the monitor fresh either way.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer

from claude_acc_manager.tui.widgets import AccountsPanel

if TYPE_CHECKING:
    from claude_acc_manager.tui.app import CamApp


class DashboardScreen(Screen[None]):
    """Landing screen — the accounts monitor plus the action menu."""

    BINDINGS = [
        Binding("q", "app.quit", "Quit"),
        Binding("f", "app.refresh_full", "Refresh usage", show=False),
    ]

    app: CamApp

    def compose(self) -> ComposeResult:
        """The monitor; the action menu arrives with the dashboard slice."""
        yield AccountsPanel(id="accounts-panel")
        yield Footer()


class WatchScreen(Screen[None]):
    """Live monitor — stacked over the dashboard; Esc pops back to it."""

    BINDINGS = [
        Binding("escape", "pop_back", "Back", show=False),
        Binding("q", "app.quit", "Quit", show=False),
    ]

    app: CamApp

    def compose(self) -> ComposeResult:
        """The same monitor, read-only."""
        yield AccountsPanel(id="accounts-panel")
        yield Footer()

    def action_pop_back(self) -> None:
        """Esc pops back to the dashboard stacked below."""
        self.app.pop_screen()
