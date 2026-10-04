"""Command-palette hits — the menu's leaves plus per-account switches.

One provider feeds Textual's palette: the nav/action commands mirror the
dashboard menu's leaf rows (the submenu trees stay menu-shaped — picking
an account there already has its own affordances), and every switchable
snapshot account gets a ``switch to '<name>'`` hit.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING, NamedTuple, cast

from textual.command import DiscoveryHit, Hit, Hits, Provider

from claude_acc_manager.accounts.application.use_cases.collect_accounts_view import (
    AccountView,
)

if TYPE_CHECKING:
    from claude_acc_manager.tui.app import CamApp


class PaletteCommand(NamedTuple):
    """One palette row: the matched text, the callback, the help line."""

    command: str
    callback: Callable[[], None]
    help: str


class CamCommandsProvider(Provider):
    """cam's palette feed: nav/action commands, then switch hits."""

    async def search(self, query: str) -> Hits:
        """Fuzzy-match every command name; ``score>0`` keeps the noise out."""
        matcher = self.matcher(query)
        for entry in self._commands():
            score = matcher.match(entry.command)
            # textual's fuzzy floor is 2.0 for any hit — every `> N` mutant
            # selects the same set, so the threshold is unkillable by design.
            if score > 0:  # pragma: no mutate
                yield Hit(
                    score,
                    matcher.highlight(entry.command),
                    entry.callback,
                    help=entry.help,
                )

    async def discover(self) -> Hits:
        """The empty-query list — every command, in menu order."""
        for entry in self._commands():
            yield DiscoveryHit(entry.command, entry.callback, help=entry.help)

    def _commands(self) -> list[PaletteCommand]:
        """Static nav/actions, then one switch hit per switchable account."""
        # cast's type arg is erased at runtime — its mutants can't differ.
        app = cast("CamApp", self.app)  # pragma: no mutate
        commands = [
            PaletteCommand(
                "switch account…",
                app.action_open_switch,
                "Pick an account to switch the live login to.",
            ),
            PaletteCommand(
                "watch accounts",
                app.action_open_watch,
                "Open the hands-off account monitor.",
            ),
            PaletteCommand(
                "auto-switch view",
                app.action_open_auto,
                "Preview the auto-switch engine's pick.",
            ),
            PaletteCommand(
                "settings…",
                app.action_open_settings,
                "Edit settings.json without leaving the TUI.",
            ),
            PaletteCommand(
                "refresh usage",
                app.action_refresh_full,
                "Ask for a usage pass now.",
            ),
            PaletteCommand(
                "toggle theme",
                app.action_toggle_theme,
                "Flip between the dark and light theme.",
            ),
            PaletteCommand("quit", app.exit, "Leave the TUI."),
        ]
        snap = app.snapshot
        for row in snap.accounts if snap is not None else ():
            if _switchable(row):
                name = row.account.name.value
                commands.append(
                    PaletteCommand(
                        f"switch to {name!r}",
                        partial(app.do_switch, name),
                        f"Switch the live login to {name!r}.",
                    )
                )
        return commands


def _switchable(row: AccountView) -> bool:
    """The use case's target set, from snapshot flags alone.

    ``has_credentials`` skips the active row automatically — the live
    credential sits in the live slot, so its parked dir reads empty.
    """
    account = row.account
    return account.enabled and not row.is_quarantined and not row.is_active and row.has_credentials
