"""Modal screens — today only ``ConfirmModal``, the destructive-guard.

The modal dismisses with ``True`` only on an explicit confirm (the action
button or ``y``); every other exit — ``n``, Esc, Cancel — answers
``False``. Nothing runs on a stray click or a dismissed screen.
"""

from __future__ import annotations

from textual import getters, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Label, Static


class ConfirmModal(ModalScreen[bool]):
    """Yes/no confirmation — dismisses ``True`` only on explicit confirm.

    Keyboard-first: y/n answer directly, ←/→ move between the buttons and
    Enter presses the focused one, Esc cancels.

    Example:
        app.push_screen(ConfirmModal("Remove 'work'?", yes_label="Remove"), on_answer)
    """

    BINDINGS = [
        Binding("y", "confirm", "Yes", show=False),
        Binding("n,escape", "cancel", "No", show=False),
        Binding("left", "app.focus_previous", show=False),
        Binding("right", "app.focus_next", show=False),
    ]

    yes_button = getters.query_one("#yes", Button)
    no_button = getters.query_one("#no", Button)

    def __init__(self, message: str, *, title: str = "Confirm", yes_label: str = "Yes") -> None:
        """Store the prompt text; *yes_label* names the destructive verb."""
        super().__init__()
        self._title = title
        self._message = message
        self._yes_label = yes_label

    def compose(self) -> ComposeResult:
        """Title, the question, two buttons, and a key hint."""
        with Vertical(classes="modal-box"):
            yield Label(self._title, classes="modal-title")
            yield Static(self._message, classes="modal-body")
            with Horizontal(classes="modal-buttons"):
                yield Button(self._yes_label, id="yes")
                yield Button("Cancel", id="no")
            yield Static(
                f"← → · enter  ·  y {self._yes_label.lower()}  ·  n / esc cancel",
                classes="modal-hint",
            )

    @property
    def focus_chain(self) -> list[Widget]:
        """The two-stop chain: action button, then Cancel."""
        return [self.yes_button, self.no_button]

    @on(Button.Pressed, "#yes")
    def on_yes_pressed(self) -> None:
        """The action button confirms."""
        self.dismiss(True)

    @on(Button.Pressed, "#no")
    def on_no_pressed(self) -> None:
        """Cancel dismisses."""
        self.dismiss(False)

    def action_confirm(self) -> None:
        """`y` answers yes."""
        self.dismiss(True)

    def action_cancel(self) -> None:
        """`n` and Esc answer no."""
        self.dismiss(False)
