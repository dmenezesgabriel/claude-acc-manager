"""The dashboard screen.

The dashboard pairs the always-visible accounts monitor with a nested
action menu; the arrow keys drive the *menu*, not the accounts. Anything
account-targeted opens a submenu of its own — remove lists every account,
enable/disable labels each row with the state it will flip to.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from textual import events, getters, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Footer, ListView, Static

from claude_acc_manager.accounts.application.use_cases.collect_accounts_view import (
    AccountView,
)
from claude_acc_manager.tui.throbber import Throbber
from claude_acc_manager.tui.widgets import AccountsPanel, ChromeStatic, MenuItem

if TYPE_CHECKING:
    from claude_acc_manager.tui.app import CamApp


class MenuEntry(NamedTuple):
    """One menu row: label, the action id it dispatches, its one-key accelerator."""

    label: str
    action_id: str
    key: str | None = None


MenuEntries = list[MenuEntry]
"""The rows of one menu depth."""

_BACK = MenuEntry("← back", "back")


def _row_key(index: int) -> str | None:
    """The accelerator for account row *index* — digits 1-9, then a-f."""
    if index < 9:
        return str(index + 1)
    if index < 15:
        return chr(ord("a") + index - 9)
    return None


_NAV = Binding.Group("Navigate")
_MENU = Binding.Group("Menu")


class DashboardScreen(Screen[None]):
    """Landing screen — the accounts monitor plus the action menu."""

    HELP = """\
The top panel watches every managed account: the live one full-size, the
rest as one-line summaries.

The menu drives every action — ↓/↑ or j/k move, Enter selects, Esc backs
out. Rows marked … open a submenu; each row also answers to the key shown
on it."""

    BINDING_GROUP_TITLE = "dashboard"
    # Terminal window title while this screen is on top — cam has no Header.
    TITLE = "dashboard"
    BINDINGS = [
        Binding(
            "s",
            "app.open_switch",
            "Switch accounts",
            tooltip="Pick an account to switch the live login to.",
            group=_NAV,
        ),
        Binding(
            "w",
            "app.open_watch",
            "Watch",
            show=False,
            tooltip="Open the hands-off account monitor.",
            group=_NAV,
        ),
        Binding(
            "g",
            "app.open_auto",
            "Auto view",
            show=False,
            tooltip="Preview the auto-switch engine's pick.",
            group=_NAV,
        ),
        Binding(
            "escape,left",
            "menu_back",
            "Back",
            show=False,
            key_display="esc/←",
            tooltip="Back one menu level.",
            group=_MENU,
        ),
        Binding("q", "app.quit", "Quit", tooltip="Leave the TUI.", group=_MENU),
        Binding(
            "f",
            "app.refresh_full",
            "Refresh usage",
            show=False,
            tooltip="Ask for a usage pass now.",
            group=_MENU,
        ),
        Binding("j", "menu_down", show=False, tooltip="Move the menu cursor down.", group=_MENU),
        Binding("k", "menu_up", show=False, tooltip="Move the menu cursor up.", group=_MENU),
    ]
    AUTO_FOCUS = "#menu"

    app: CamApp

    menu = getters.query_one("#menu", ListView)
    menu_title = getters.query_one("#menu-title", Static)

    def __init__(self) -> None:
        """The menu is a stack of (title, entries); depth 1 is root."""
        super().__init__()
        self._menu_stack: list[tuple[str, MenuEntries]] = []

    def compose(self) -> ComposeResult:
        """Monitor on top, breadcrumb + throbber, and the menu list below."""
        yield AccountsPanel(id="accounts-panel")
        with Horizontal(id="menu-title-row"):
            yield ChromeStatic(id="menu-title")
            yield Throbber(id="throbber")
        yield ListView(id="menu")
        yield Footer()

    async def on_mount(self) -> None:
        """Render the root entries; AUTO_FOCUS lands on the menu."""
        self.app.update_terminal_title()
        await self._push_menu("menu", self._root_entries())

    def on_screen_resume(self) -> None:
        """A stacked screen left — restore this screen's window title."""
        self.app.update_terminal_title()

    # -- menu plumbing --------------------------------------------------------

    def _root_entries(self) -> MenuEntries:
        """The top level; add stays CLI-side (interactive login)."""
        return [
            MenuEntry("Switch account…", "switch", "s"),
            MenuEntry("Watch accounts", "watch", "w"),
            MenuEntry("Auto-switch view", "auto", "g"),
            MenuEntry("Enable / disable account…", "disable-menu", "e"),
            MenuEntry("Remove account…", "remove-menu", "r"),
            MenuEntry("Theme…", "theme-menu", "t"),
            MenuEntry("Quit", "quit", "q"),
        ]

    def _toggle_entries(self) -> MenuEntries:
        """One row per account, labelled with the flip selecting it takes."""
        snap = self.app.snapshot
        entries: MenuEntries = []
        for i, row in enumerate(snap.accounts if snap else ()):
            account = row.account
            action = "→ enable" if not account.enabled else "→ disable"
            state = "  (disabled)" if not account.enabled else ""
            label = f"{self._account_label(row)}{state}   {action}"
            entries.append(MenuEntry(label, f"disable:{account.name.value}", _row_key(i)))
        entries.append(_BACK)
        return entries

    def _remove_entries(self) -> MenuEntries:
        """One row per account; selection confirms before deleting."""
        snap = self.app.snapshot
        entries: MenuEntries = [
            MenuEntry(
                self._account_label(row),
                f"remove:{row.account.name.value}",
                _row_key(i),
            )
            for i, row in enumerate(snap.accounts if snap else ())
        ]
        entries.append(_BACK)
        return entries

    def _account_label(self, row: AccountView) -> str:
        """``name (email)`` — the shared submenu row label."""
        account = row.account
        if account.email:
            return f"{account.name.value} ({account.email})"
        return account.name.value

    def _theme_entries(self) -> MenuEntries:
        """Dark / light with the active one marked."""
        current = self.app.theme_name
        entries: MenuEntries = [
            MenuEntry(f"{'●' if name == current else ' '} {name}", f"theme:{name}", key)
            for name, key in (("dark", "d"), ("light", "l"))
        ]
        entries.append(_BACK)
        return entries

    async def _push_menu(self, title: str, entries: MenuEntries) -> None:
        """Descend one level: record it, then repaint title + rows."""
        self._menu_stack.append((title, entries))
        await self._render_menu()

    async def _pop_menu(self) -> None:
        """Ascend one level; at root, Esc/left is a no-op."""
        if len(self._menu_stack) > 1:
            self._menu_stack.pop()
            await self._render_menu()

    async def _render_menu(self) -> None:
        """Paint the top of the stack: ``a › b`` crumb + its rows."""
        entries = self._menu_stack[-1][1]
        crumb = " › ".join(t for t, _ in self._menu_stack)
        self.menu_title.update(crumb)
        menu = self.menu
        await menu.clear()
        await menu.extend(
            MenuItem(entry.label, entry.action_id, muted=(entry.action_id == "back"), key=entry.key)
            for entry in entries
        )
        menu.index = 0

    @on(ListView.Selected, "#menu")
    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Enter on a menu row dispatches its action id."""
        item = event.item
        if isinstance(item, MenuItem):
            await self._dispatch(item.action_id)

    @on(events.Key)
    def _on_menu_accelerator(self, event: events.Key) -> None:
        """A key matching a visible row highlights it and selects it.

        Rows only claim keys they print; anything else (j/k, Esc, bound
        shortcuts) propagates to the binding layer untouched.
        """
        keys = {item.key: index for index, item in enumerate(self.menu.query(MenuItem))}
        index = keys.get(event.key)
        if index is None:
            return
        self.menu.index = index
        event.stop()
        self.menu.action_select_cursor()

    async def _dispatch(self, action_id: str) -> None:
        """Route a row: ascend, descend into a submenu, or run an action."""
        if action_id == "back":
            await self._pop_menu()
        elif action_id.endswith("-menu"):
            await self._push_submenu(action_id)
        else:
            await self._dispatch_leaf(action_id)

    async def _push_submenu(self, action_id: str) -> None:
        """Open the submenu a ``*-menu`` row names."""
        if action_id == "disable-menu":
            await self._push_menu("enable / disable", self._toggle_entries())
        elif action_id == "remove-menu":
            await self._push_menu("remove account", self._remove_entries())
        elif action_id == "theme-menu":
            await self._push_menu("theme", self._theme_entries())

    async def _dispatch_leaf(self, action_id: str) -> None:
        """Run or open what a non-submenu row selects, then settle the menu."""
        app = self.app
        if action_id == "switch":
            app.action_open_switch()
        elif action_id == "watch":
            app.action_open_watch()
        elif action_id == "auto":
            app.action_open_auto()
        elif action_id == "quit":
            app.exit()
        elif action_id.startswith("theme:"):
            app.apply_theme(action_id.removeprefix("theme:"))
            await self._pop_menu()
        elif action_id.startswith("disable:"):
            app.do_toggle_enabled(action_id.removeprefix("disable:"))
            await self._pop_menu()
        elif action_id.startswith("remove:"):
            app.confirm_remove(action_id.removeprefix("remove:"))
            await self._pop_menu()

    # -- menu-bound actions -----------------------------------------------------

    async def action_menu_back(self) -> None:
        """Esc/left ascends one menu level."""
        await self._pop_menu()

    def action_menu_down(self) -> None:
        """`j` mirrors ↓ on the menu list."""
        self.menu.action_cursor_down()

    def action_menu_up(self) -> None:
        """`k` mirrors ↑ on the menu list."""
        self.menu.action_cursor_up()
