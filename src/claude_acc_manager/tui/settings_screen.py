"""The settings modal — one generated editor row per ``SETTING_SPECS`` key.

Rows come from the app's ``settings_rows()`` — the same ``EffectiveSetting``
tuples ``cam config list`` prints — so the editor can never drift from the
schema. Seeds are applied under ``prevent(Changed)`` so mounting a value
never masquerades as an edit; the actual write path is T7.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.validation import Number
from textual.widgets import Footer, Input, Select

from claude_acc_manager.settings.domain.settings_spec import (
    EffectiveSetting,
    format_setting_value,
)
from claude_acc_manager.tui.widgets import ChromeStatic

if TYPE_CHECKING:
    from claude_acc_manager.tui.app import CamApp


class SettingsScreen(ModalScreen[None]):
    """Generated editor for the ``autoswitch`` settings keys."""

    HELP = """\
Each row is one ``settings.json`` key. Number fields validate against the
key's range; the strategy row is a fixed choice. Esc leaves."""

    BINDING_GROUP_TITLE = "settings"
    TITLE = "settings"
    BINDINGS = [
        Binding("escape", "dismiss", "Back", tooltip="Leave the settings screen."),
    ]

    app: CamApp

    def compose(self) -> ComposeResult:
        """One labelled editor per spec key, seeded with effective values."""
        with VerticalScroll(id="settings"):
            yield ChromeStatic("settings", id="settings-title")
            for row in self.app.settings_rows():
                yield from self._editor(row)
        yield Footer()

    def _editor(self, row: EffectiveSetting) -> ComposeResult:
        """A float key gets a bounded number Input; a choice key a Select."""
        with Vertical(classes="setting"):
            yield ChromeStatic(row.spec.dotted, classes="setting-name")
            yield ChromeStatic(row.spec.help, classes="setting-help")
            if row.spec.kind == "choice":
                # prevent() guards a future Changed-on-seed; on textual 8.2.8
                # constructor values emit nothing, so the mutant is equivalent.
                with self.prevent(Select.Changed):  # pragma: no mutate
                    yield Select(
                        [(choice, choice) for choice in row.spec.choices],
                        value=str(row.value),
                        id=f"setting-{row.spec.field}",
                        allow_blank=False,
                    )
            else:
                # Same defensive guard — unseeded Inputs emit no Changed.
                with self.prevent(Input.Changed):  # pragma: no mutate
                    yield Input(
                        format_setting_value(row.value),
                        type="number",
                        validators=[Number(minimum=row.spec.lo, maximum=row.spec.hi)],
                        id=f"setting-{row.spec.field}",
                    )

    def on_mount(self) -> None:
        """The window title follows the pushed screen."""
        self.app.update_terminal_title()
