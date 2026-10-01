"""Account-list screens — a live ``ListView`` of full account cards.

:class:`AccountListScreen` owns the snapshot plumbing every account list
shares: rebuild rows when membership changes, repaint them in place when
it doesn't, keep the cursor where the user left it, and flash a row whose
measurement just advanced. Subclasses decide what the cursor does —
:class:`SwitchScreen` is selection-first; T10's armed ``WatchScreen``
reuses the same list machinery as a monitor.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, ListView, Static

from claude_acc_manager.accounts.application.use_cases.collect_accounts_view import (
    AccountsView,
)
from claude_acc_manager.tui.widgets import AccountItem

if TYPE_CHECKING:
    from claude_acc_manager.tui.app import CamApp

FLASH_S = 1.5  # how long a just-refreshed row stays highlighted


class AccountListScreen(Screen[None]):
    """Shared machinery: a live ListView of full account cards."""

    app: CamApp

    def __init__(self) -> None:
        """Track membership (row identity) and per-account freshness."""
        super().__init__()
        self._names: list[str] = []
        self._stamps: dict[str, float | None] = {}

    def compose(self) -> ComposeResult:
        """A title line above the account list."""
        yield Static(id="list-title")
        yield ListView(id="accounts")
        yield Footer()

    def on_mount(self) -> None:
        """Watch the app snapshot; ``init=True`` paints the current one now."""
        self.watch(self.app, "snapshot", self._on_snapshot)

    async def _on_snapshot(self, snap: AccountsView | None) -> None:
        """Rebuild on membership change; otherwise update rows in place."""
        if snap is None:
            return
        # the type arg only narrows a unique selector — mutmut-equivalent
        listview = self.query_one("#accounts", ListView)  # pragma: no mutate
        names = [row.account.name.value for row in snap.accounts]
        if names != self._names:
            first_build = not self._names
            previous = listview.index
            await listview.clear()
            await listview.extend(AccountItem(row) for row in snap.accounts)
            self._names = names
            listview.index = self._index_after_build(snap, first_build, previous) if names else None
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
        # the type arg only narrows a unique selector — mutmut-equivalent
        self.query_one("#accounts", ListView).action_cursor_down()  # pragma: no mutate

    def action_menu_up(self) -> None:
        """`k` mirrors ↑ on the account list."""
        # the type arg only narrows a unique selector — mutmut-equivalent
        self.query_one("#accounts", ListView).action_cursor_up()  # pragma: no mutate


class SwitchScreen(AccountListScreen):
    """All accounts, full-size and alive: arrows pick, Enter switches."""

    BINDINGS = [
        # priority: outranks the focused ListView's own (hidden) enter binding
        # so "Switch" shows in the footer; the action delegates right back to
        # the list cursor, so behavior is identical.
        Binding("enter", "select_highlighted", "Switch", priority=True),
        Binding("b", "app.switch_best", "Best pick"),
        Binding("escape,q,s", "back", "Back"),
        Binding("j", "menu_down", show=False),
        Binding("k", "menu_up", show=False),
    ]

    def on_mount(self) -> None:
        """Set the title, focus the list, then hook the snapshot watch."""
        # the type args only narrow a unique selector — mutmut-equivalent
        title = self.query_one("#list-title", Static)  # pragma: no mutate
        title.update("switch to which account?")
        self.query_one("#accounts", ListView).focus()  # pragma: no mutate
        super().on_mount()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Enter on a row switches the live login to that account."""
        item = event.item
        if isinstance(item, AccountItem):
            self.app.do_switch(item.account_name.value)
            self.app.pop_screen()

    def action_select_highlighted(self) -> None:
        """The footer's Enter delegates to the list's own selection."""
        # the type arg only narrows a unique selector — mutmut-equivalent
        listview = self.query_one("#accounts", ListView)  # pragma: no mutate
        if listview.display:
            listview.action_select_cursor()

    def action_back(self) -> None:
        """Esc/q/s pop back to whatever pushed this screen."""
        self.app.pop_screen()
