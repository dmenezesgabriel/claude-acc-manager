"""The TUI's single-flight mutating-action lane.

Every account mutation funnels through one busy-gated thread worker, so a
keypress can never overlap a switch/remove already in flight — and every
completion repaints from the post-action world (refresh + unfocused title
blink + toast). The host ``CamApp`` keeps the binding surface; this class
owns the orchestration so ``tui/app.py`` stays under the file ceiling.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING, NamedTuple, TypeVar

from textual.notifications import SeverityLevel

from claude_acc_manager.accounts.application.switch_message import switch_message
from claude_acc_manager.accounts.application.use_cases.collect_accounts_view import (
    AccountView,
)
from claude_acc_manager.accounts.application.use_cases.switch_account import SwitchResult
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.tui.formatting import email_fragment
from claude_acc_manager.tui.modals import ConfirmModal
from claude_acc_manager.tui.ports import TuiUseCases

if TYPE_CHECKING:
    from claude_acc_manager.tui.app import CamApp

# PEP 695 generics (`def f[T]`) parse only on 3.12+; the supported floor is
# 3.11, so the three lane helpers share this plain TypeVar instead.
_T = TypeVar("_T")


class ActionToast(NamedTuple):
    """A finished action's toast: message plus severity."""

    message: str
    severity: SeverityLevel


def _switch_toast(result: SwitchResult) -> ActionToast:
    """Switches toast info on a move, warning on a non-move outcome."""
    return ActionToast(
        switch_message(result),
        "information" if result.outcome == "switched" else "warning",
    )


class ActionRunner:
    """Single-flight lane for mutating actions, off the UI loop.

    ``@work`` cannot live on a plain object (the decorator asserts its
    receiver is a ``DOMNode``), so the lane spawns through the host app's
    ``run_worker`` — the per-action identity rides ``name=label``.
    """

    def __init__(self, app: CamApp, use_cases: TuiUseCases) -> None:
        """Hold the host's UI seams and the injected use cases."""
        self._app = app
        self._use_cases = use_cases

    # -- entry points -------------------------------------------------------

    def switch(self, name: str) -> None:
        """Switch the live login to *name*; the outcome arrives as a toast.

        Example:
            ``app.actions.switch("personal")`` → toast ``switched to 'personal' …``
        """
        self._start(
            f"switch to {name}",
            lambda: self._use_cases.switch.execute(AccountName(name)),
            _switch_toast,
            "switch failed",
        )

    def switch_best(self) -> None:
        """`b` — strategy=``best`` over the snapshot's cached headroom."""
        self._start(
            "switch (best)",
            lambda: self._use_cases.switch.execute(
                strategy="best", headroom=self._app.headroom_map()
            ),
            _switch_toast,
            "switch failed",
        )

    def toggle_enabled(self, name: str) -> None:
        """Flip *name*'s enabled flag; the toast names the new state.

        Example:
            ``app.actions.toggle_enabled("work")`` → toast ``disabled account 'work'``
        """
        row = self._snapshot_row(name)
        if row is None:
            self._app.notify(f"no account named {name!r}", severity="warning")
            return
        enabled = not row.account.enabled
        self._start(
            f"toggle {name}",
            lambda: self._use_cases.set_enabled.execute(AccountName(name), enabled),
            lambda account: ActionToast(
                f"{'enabled' if account.enabled else 'disabled'} account {name!r}",
                "information",
            ),
            "toggle failed",
        )

    def confirm_remove(self, name: str) -> None:
        """Ask before deleting *name* — the modal answers True only on yes.

        Example:
            ``app.actions.confirm_remove("work")`` → "Remove account 'work' (…)?"
        """
        self._app.push_screen(
            ConfirmModal(
                self._remove_message(name),
                title="Remove account",
                yes_label="Remove",
            ),
            partial(self._on_remove_answer, name),
        )

    def remove(self, name: str) -> None:
        """Delete *name*'s registry entry and parked login dir.

        Example:
            ``app.actions.remove("work")`` → toast ``removed account 'work'``
        """
        self._start(
            f"remove {name}",
            lambda: self._use_cases.remove.execute(AccountName(name)),
            lambda _result: ActionToast(f"removed account {name!r}", "information"),
            "remove failed",
        )

    # -- lane ---------------------------------------------------------------

    def _start(
        self,
        label: str,
        call: Callable[[], _T],
        toast: Callable[[_T], ActionToast],
        failure: str,
    ) -> None:
        """Single-flight a mutating action in a thread worker."""
        if self._app.busy:
            self._app.notify("another action is still running", severity="warning")
            return
        self._app.busy = True
        self._app.run_worker(
            partial(self._blocking, call, toast, failure),
            thread=True,
            group="action",
            name=label,
            exit_on_error=False,
        )

    def _blocking(
        self,
        call: Callable[[], _T],
        toast: Callable[[_T], ActionToast],
        failure: str,
    ) -> None:
        """Run the use case off the event loop, then post the outcome."""
        try:
            result: _T | Exception = call()
        except Exception as exc:
            result = exc
        self._app.call_from_thread(self._done, result, toast, failure)

    def _done(
        self,
        result: _T | Exception,
        toast: Callable[[_T], ActionToast],
        failure: str,
    ) -> None:
        """Free the lane, repaint from the post-action world, and toast."""
        self._app.busy = False
        self._app.request_refresh()
        self._app.blink_terminal_title()
        if isinstance(result, Exception):
            self._app.notify(f"{failure}: {result}", severity="error", timeout=8)
            return
        done = toast(result)
        self._app.notify(done.message, severity=done.severity)

    # -- modal + snapshot helpers ---------------------------------------------

    def _on_remove_answer(self, name: str, confirmed: bool | None) -> None:
        """The modal callback — the remove runs only on an explicit yes."""
        if confirmed:
            self.remove(name)

    def _snapshot_row(self, name: str) -> AccountView | None:
        """The snapshot row for *name*, or None when absent/unsnapshotted."""
        snap = self._app.snapshot
        return next(
            (r for r in (snap.accounts if snap else ()) if r.account.name.value == name),
            None,
        )

    def _remove_message(self, name: str) -> str:
        """The confirm body; removing the live account leaves it unmanaged."""
        row = self._snapshot_row(name)
        email = ""
        if row is not None:
            email = email_fragment(row.account, redact=self._app.redact_emails)
        lines = [
            f"Remove account {name!r}{email}?",
            "",
            "Its stored login directory is deleted.",
        ]
        if row is not None and row.is_active:
            lines.append(f"{name!r} is the live account — the login stays, unmanaged.")
        return "\n".join(lines)
