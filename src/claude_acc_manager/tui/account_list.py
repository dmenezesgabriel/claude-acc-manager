"""Account-list screens — a live ``ListView`` of full account cards.

:class:`AccountListScreen` owns the snapshot plumbing every account list
shares: rebuild rows when membership changes, repaint them in place when
it doesn't, keep the cursor where the user left it, and flash a row whose
measurement just advanced. Subclasses decide what the cursor does —
:class:`SwitchScreen` is selection-first; the armed ``WatchScreen``
reuses the same list machinery as a monitor.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from textual import getters, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Footer, ListView, Static

from claude_acc_manager.accounts.application.use_cases.collect_accounts_view import (
    AccountsView,
)
from claude_acc_manager.tui.throbber import Throbber
from claude_acc_manager.tui.widgets import AccountItem, ChromeStatic

if TYPE_CHECKING:
    from claude_acc_manager.tui.app import CamApp

FLASH_S = 1.5  # how long a just-refreshed row stays highlighted


class AccountListScreen(Screen[None]):
    """Shared machinery: a live ListView of full account cards."""

    app: CamApp

    account_list = getters.query_one("#accounts", ListView)
    list_title = getters.query_one("#list-title", Static)

    def __init__(self) -> None:
        """Track membership (row identity) and per-account freshness."""
        super().__init__()
        self._names: list[str] = []
        self._stamps: dict[str, float | None] = {}

    def compose(self) -> ComposeResult:
        """A title line (with the throbber) above the account list."""
        with Horizontal(id="list-title-row"):
            yield ChromeStatic(id="list-title")
            yield Throbber(id="throbber")
        yield ListView(id="accounts")
        yield Footer()

    def on_mount(self) -> None:
        """Watch the app snapshot; ``init=True`` paints the current one now."""
        self.app.update_terminal_title()
        self.watch(self.app, "snapshot", self._on_snapshot)

    def on_screen_resume(self) -> None:
        """A stacked screen/modal left — restore this screen's title."""
        self.app.update_terminal_title()

    async def _on_snapshot(self, snap: AccountsView | None) -> None:
        """Rebuild on membership change; otherwise update rows in place."""
        if snap is None:
            return
        listview = self.account_list
        names = [row.account.name.value for row in snap.accounts]
        if names != self._names:
            first_build = not self._names
            previous = listview.index
            await listview.clear()
            await listview.extend(AccountItem(row) for row in snap.accounts)
            self._names = names
            # an empty `names` means the list was just rebuilt to zero rows —
            # ListView.validate_index clamps any int to None on an empty
            # _nodes, so the `or True` mutant's computed index is equivalent.
            if names:  # pragma: no mutate
                listview.index = self._index_after_build(snap, first_build, previous)
            else:
                # _nodes is empty here — validate_index clamps any assigned
                # value to None, so literal mutants are equivalent.
                listview.index = None  # pragma: no mutate
        else:
            # equal membership implies equal row count — strict guards a
            # can't-happen shape (a missing widget), so it's equivalent-prone
            items = listview.query(AccountItem)
            for item, row in zip(items, snap.accounts, strict=True):  # pragma: no mutate
                item.set_account(row)
        self._flash_updated(snap, listview)

    def _index_after_build(
        self, snap: AccountsView, first_build: bool, previous: int | None
    ) -> int | None:
        """Where the cursor lands after the list is (re)built."""
        if first_build:
            return self._active_index(snap)
        return min(previous or 0, len(snap.accounts) - 1)

    def _active_index(self, snap: AccountsView) -> int:
        """The row index of the live account; 0 when unmanaged/absent."""
        return next(
            (
                i
                for i, row in enumerate(snap.accounts)
                if row.account.name.value == snap.active_name
            ),
            0,
        )

    def _flash_updated(self, snap: AccountsView, listview: ListView) -> None:
        """Briefly highlight rows whose stored measurement just advanced."""
        new_stamps = {row.account.name.value: row.usage.fetched_at_s for row in snap.accounts}
        if self._stamps:
            changed = {
                name
                for name, ts in new_stamps.items()
                if ts is not None and ts != self._stamps.get(name)
            }
            for item in listview.query(AccountItem):
                if item.account_name.value in changed and not item.has_class("flash"):
                    item.add_class("flash")
                    self.set_timer(FLASH_S, partial(item.remove_class, "flash"))
        self._stamps = new_stamps

    def action_menu_down(self) -> None:
        """`j` mirrors ↓ on the account list."""
        self.account_list.action_cursor_down()

    def action_menu_up(self) -> None:
        """`k` mirrors ↑ on the account list."""
        self.account_list.action_cursor_up()


class SwitchScreen(AccountListScreen):
    """All accounts, full-size and alive: arrows pick, Enter switches."""

    HELP = """\
Every managed account, full-size and live. ↓/↑ or j/k move the cursor;
Enter switches the live login to the highlighted account. `b` skips the
list and picks the best headroom. Esc returns."""

    BINDING_GROUP_TITLE = "switch"
    TITLE = "switch"
    BINDINGS = [
        # priority: outranks the focused ListView's own (hidden) enter binding
        # so "Switch" shows in the footer; the action delegates right back to
        # the list cursor, so behavior is identical.
        Binding(
            "enter",
            "select_highlighted",
            "Switch",
            priority=True,
            tooltip="Switch the live login to the highlighted account.",
        ),
        Binding(
            "b",
            "app.switch_best",
            "Best pick",
            tooltip="Switch to the account with the most headroom.",
        ),
        Binding(
            "escape,q,s",
            "back",
            "Back",
            key_display="esc/q/s",
            tooltip="Back to the dashboard.",
        ),
        Binding("j", "menu_down", show=False, tooltip="Move the cursor down."),
        Binding("k", "menu_up", show=False, tooltip="Move the cursor up."),
    ]
    AUTO_FOCUS = "#accounts"

    def on_mount(self) -> None:
        """Set the title, then hook the snapshot watch; AUTO_FOCUS lands on the list."""
        title = self.list_title
        title.update("switch to which account?")
        super().on_mount()

    @on(ListView.Selected, "#accounts")
    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Enter on a row switches the live login to that account."""
        item = event.item
        if isinstance(item, AccountItem):
            self.app.do_switch(item.account_name.value)
            self.app.pop_screen()

    def action_select_highlighted(self) -> None:
        """The footer's Enter delegates to the list's own selection."""
        listview = self.account_list
        if listview.display:
            listview.action_select_cursor()

    def action_back(self) -> None:
        """Esc/q/s pop back to whatever pushed this screen."""
        self.app.pop_screen()


class WatchScreen(AccountListScreen):
    """Live monitor of every account, full detail, hands-off by default.

    ``s`` arms selection (cursor appears on the active account); Enter then
    switches and stays here — you keep watching on the new account. Esc
    disarms selection first, then leaves the screen.
    """

    HELP = """\
A hands-off monitor: every account, full detail, refreshed live. The title
line reports snapshot age and refresh progress.

`s` arms selection — a cursor appears on the live account; Enter switches
to the highlighted one and keeps watching. Esc disarms first, then exits."""

    _WATCH_TITLE = "watching all accounts"
    _SELECT_TITLE = "switch to which account? · enter confirm · esc cancel"

    BINDING_GROUP_TITLE = "watch"
    TITLE = "watch"
    BINDINGS = [
        Binding(
            "s",
            "toggle_select",
            "Switch",
            tooltip="Arm the selection cursor to switch from here.",
        ),
        Binding(
            "enter",
            "select_highlighted",
            "Confirm",
            priority=True,
            tooltip="Switch to the highlighted account (while armed).",
        ),
        Binding(
            "f",
            "app.refresh_full",
            "Refresh",
            show=False,
            tooltip="Ask for a usage pass now.",
        ),
        Binding(
            "escape,q",
            "back",
            "Back",
            key_display="esc/q",
            tooltip="Disarm selection, then leave.",
        ),
        Binding(
            "down,j",
            "nav_down",
            show=False,
            key_display="↓/j",
            tooltip="Move the cursor down (or scroll while watching).",
        ),
        Binding(
            "up,k",
            "nav_up",
            show=False,
            key_display="↑/k",
            tooltip="Move the cursor up (or scroll while watching).",
        ),
    ]

    def __init__(self) -> None:
        """Monitor mode starts disarmed — no cursor until ``s``."""
        super().__init__()
        self._selecting = False

    def on_mount(self) -> None:
        """Title tracks the refresh status; the watch hook rides on top."""
        self.watch(self.app, "refresh_status", self._on_refresh_status)
        title = self.list_title
        title.update(self._title_text())
        super().on_mount()

    def _title_text(self) -> str:
        """Monitor title plus live status, or the armed-selection prompt."""
        if self._selecting:
            return self._SELECT_TITLE
        status = self.app.refresh_status
        return f"{self._WATCH_TITLE} · {status}" if status else self._WATCH_TITLE

    def _on_refresh_status(self, status: str) -> None:
        """An armed title is the prompt — status never overwrites it."""
        if self._selecting:
            return
        title = self.list_title
        title.update(self._title_text())

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Confirm is hidden and inert until selection is armed."""
        del parameters  # textual's signature demands it; the action decides
        if action == "select_highlighted" and not self._selecting:
            return False
        return True

    def _index_after_build(
        self, snap: AccountsView, first_build: bool, previous: int | None
    ) -> int | None:
        """Monitor mode keeps no cursor even across rebuilds."""
        if not self._selecting:
            return None
        return super()._index_after_build(snap, first_build, previous)

    def _set_selecting(self, on: bool) -> None:
        """Arm/disarm: cursor + prompt title on, clean monitor on off."""
        self._selecting = on
        listview = self.account_list
        title = self.list_title
        if on:
            snap = self.app.snapshot
            if snap is not None and snap.accounts:
                listview.index = self._active_index(snap)
            listview.focus()
            title.update(self._SELECT_TITLE)
        else:
            listview.index = None
            self.set_focus(None)
            title.update(self._title_text())
        self.refresh_bindings()

    def action_toggle_select(self) -> None:
        """``s`` toggles the armed selection on the watch monitor."""
        self._set_selecting(not self._selecting)

    @on(ListView.Selected, "#accounts")
    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Enter switches while armed; a stray click while watching is inert."""
        if not self._selecting:
            return
        item = event.item
        if isinstance(item, AccountItem):
            self.app.do_switch(item.account_name.value)
            self._set_selecting(False)  # stay here, keep watching

    def action_select_highlighted(self) -> None:
        """The footer's Enter delegates to the list cursor, while armed."""
        if self._selecting:
            listview = self.account_list
            listview.action_select_cursor()

    def action_back(self) -> None:
        """Esc/q disarm first; a second press pops back."""
        if self._selecting:
            self._set_selecting(False)
        else:
            self.app.pop_screen()

    def action_nav_down(self) -> None:
        """``j``/↓ move the armed cursor, scroll the hands-off monitor."""
        listview = self.account_list
        if self._selecting:
            listview.action_cursor_down()
        else:
            listview.scroll_down(animate=False)

    def action_nav_up(self) -> None:
        """``k``/↑ move the armed cursor, scroll the hands-off monitor."""
        listview = self.account_list
        if self._selecting:
            listview.action_cursor_up()
        else:
            listview.scroll_up(animate=False)
