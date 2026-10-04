"""Widget layer: the accounts panel, list cards, and menu chrome.

The renderables themselves — bar glyphs, card parts, mini lines — live in
``tui.formatting`` (pure ``Text`` builders) and ``tui.visuals`` (the
cached-strip ``Visual`` wrappers these ``render()`` methods return). This
module is the plumbing: reactive watches, breakpoint reads, and focus.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual import getters
from textual.dom import NoScreen
from textual.reactive import var
from textual.visual import Visual
from textual.widgets import ListItem, Static

from claude_acc_manager.accounts.application.use_cases.collect_accounts_view import (
    AccountView,
)
from claude_acc_manager.tui.theme import Palette
from claude_acc_manager.tui.visuals import (
    AccountCardVisual,
    MiniAccountVisual,
    StackedVisual,
)

if TYPE_CHECKING:
    from claude_acc_manager.tui.app import CamApp

# The exact fallback width is unobservable: a 1px shift is invisible under the
# 30-cell bar cap and the suffix-fit check only bites at long labels.
_UNMOUNTED_WIDTH = 80


class AccountsPanel(Static):
    """Static account overview: the active account full-size, others as minis.

    The dashboard's — and with ``show_minis=False`` the auto screen's —
    always-visible monitor.
    """

    app: CamApp

    def __init__(self, *, show_minis: bool = True, id: str | None = None) -> None:
        """``show_minis=False`` renders only the active card."""
        super().__init__(id=id)
        self._show_minis = show_minis

    def on_mount(self) -> None:
        """Repaint on every new snapshot, theme flip, or threshold write.

        watch(), not data_bind: binds source from the active message pump,
        so app-owned reactives can only be bound from app-pumped contexts —
        a deep widget's cross-node propagation is what watch() is for.
        """
        self.watch(self.app, "snapshot", self._repaint)
        self.watch(self.app, "theme", self._repaint)
        self.watch(self.app, "threshold_pct", self._repaint)

    def _repaint(self, *_args: object) -> None:
        """Watcher-shaped repaint — watch callbacks arrive as (old, new)."""
        self.refresh(layout=True)

    def render(self) -> Text | Visual:
        """Paint the frame: loading, empty, or card + minis."""
        app = self.app
        palette = Palette.from_theme(app.current_theme)
        snap = app.snapshot
        if snap is None:
            return Text("loading…", style=palette.muted)
        if not snap.accounts:
            return Text(
                "No managed accounts yet.\nRun `cam add <name>` to register one.",
                style=palette.muted,
            )
        blocks = self._blocks(snap.accounts, app.now_s(), app.threshold_pct, palette)
        if not blocks:
            return Text("no active managed login", style=palette.muted)
        return StackedVisual(blocks)

    def _blocks(
        self,
        accounts: tuple[AccountView, ...],
        now: float,
        threshold: float,
        palette: Palette,
    ) -> list[Visual]:
        """Active account's card first, then one mini per inactive row."""
        width = self.size.width or _UNMOUNTED_WIDTH
        # Minis are optional chrome — a narrow terminal needs the columns.
        minis = self._show_minis and not self._narrow()
        blocks: list[Visual] = []
        for row in accounts:
            if row.is_active:
                blocks.append(
                    AccountCardVisual(row, width, threshold=threshold, now=now, palette=palette)
                )
            elif minis:
                blocks.append(MiniAccountVisual(row, now, palette=palette))
        return blocks

    def _narrow(self) -> bool:
        """True while the hosting screen carries the ``-narrow`` class."""
        try:
            return self.screen.has_class("-narrow")
        except NoScreen:
            return False


class AccountCard(Static):
    """One account rendered full-size (used by the switch screen's list)."""

    app: CamApp

    view: var[AccountView | None] = var(None)

    def __init__(self, view: AccountView, *, threshold: float | None = None) -> None:
        """Hold the row and the auto-switch threshold tick."""
        super().__init__()
        self.view = view
        self._threshold = threshold

    def watch_view(self) -> None:
        """A bound ``view`` change repaints the card."""
        self.refresh(layout=True)

    def render(self) -> Text | Visual:
        """Paint the card at the current width and theme."""
        app = self.app
        view = self.view
        if view is None:
            # can't happen: the ctor seeds a view before the card can render —
            # the var's default exists only because reactive defaults are
            # class-level
            return Text()
        return AccountCardVisual(
            view,
            self.size.width or _UNMOUNTED_WIDTH,
            threshold=self._threshold,
            now=app.now_s(),
            palette=Palette.from_theme(app.current_theme),
        )


class AccountItem(ListItem):
    """ListView row wrapping an :class:`AccountCard`; remembers its account."""

    card = getters.query_one(AccountCard)

    view: var[AccountView | None] = var(None)

    def __init__(self, view: AccountView) -> None:
        """Store the row's identity for selection handling."""
        # the mount-time bind re-syncs card.view; the ctor seed only covers
        # the pre-bind render window a mounted row never reaches — the
        # AccountCard(None) mutant is equivalent, hence pragma: no mutate
        super().__init__(AccountCard(view))  # pragma: no mutate
        self.set_account(view)

    def on_mount(self) -> None:
        """Bind the card's ``view`` to the row's — set_account flows through."""
        self.card.data_bind(view=AccountItem.view)

    def set_account(self, view: AccountView) -> None:
        """Refresh the stored identity; the bound card follows ``view``."""
        self.account_name = view.account.name
        self.view = view


class ChromeStatic(Static):
    """A Static that refuses text selection — titles, badges, hints."""

    ALLOW_SELECT = False


class MenuItem(ListItem):
    """One menu row: a label, an action id, an optional accelerator key."""

    ALLOW_SELECT = False

    def __init__(
        self, label: str, action_id: str, *, muted: bool = False, key: str | None = None
    ) -> None:
        """Wrap the label in a Static; ``muted`` dims it, ``key`` prefixes it."""
        text = f"{key}  {label}" if key else label
        # markup=None is falsy through visualize()'s ``if markup`` check —
        # identical to False, hence pragma: no mutate.
        item = ChromeStatic(text, markup=False)  # pragma: no mutate
        if muted:
            item.add_class("menu-item-muted")
        super().__init__(item)
        self.action_id = action_id
        self.key = key
