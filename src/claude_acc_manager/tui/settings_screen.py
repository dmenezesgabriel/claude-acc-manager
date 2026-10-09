"""The settings modal — one generated editor row per ``SETTING_SPECS`` key.

Rows come from the app's ``settings_rows()`` — the same ``EffectiveSetting``
tuples ``cam config list`` prints — so the editor can never drift from the
schema. Seeds are applied under ``prevent(Changed)`` so mounting a value
never masquerades as an edit; edits write through the app's
``apply_setting`` and revert on rejection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.validation import Number
from textual.widgets import Footer, Input, Select

from claude_acc_manager.settings.domain.settings_spec import (
    EffectiveSetting,
    SettingSpec,
    format_setting_value,
)
from claude_acc_manager.tui.widgets import ChromeStatic

if TYPE_CHECKING:
    from claude_acc_manager.tui.app import CamApp


class SettingsScreen(ModalScreen[None]):
    """Generated editor for the ``settings.json`` keys."""

    HELP = """\
Each row is one ``settings.json`` key. Number fields validate against the
key's range; choice and bool rows are fixed selects. Esc leaves."""

    BINDING_GROUP_TITLE = "settings"
    TITLE = "settings"
    BINDINGS = [
        Binding("escape", "dismiss", "Back", tooltip="Leave the settings screen."),
    ]

    app: CamApp

    def __init__(self) -> None:
        """Editor-id → spec map, populated while rows are composed."""
        super().__init__()
        self._specs: dict[str, SettingSpec] = {}

    def compose(self) -> ComposeResult:
        """One labelled editor per spec key, seeded with effective values."""
        with VerticalScroll(id="settings"):
            yield ChromeStatic("settings", id="settings-title")
            for row in self.app.settings_rows():
                yield from self._editor(row)
        yield Footer()

    def _editor(self, row: EffectiveSetting) -> ComposeResult:
        """A float key gets a bounded number Input; a choice or bool key a Select."""
        editor_id = f"setting-{row.spec.field}"
        self._specs[editor_id] = row.spec
        with Vertical(classes="setting"):
            yield ChromeStatic(row.spec.dotted, classes="setting-name")
            yield ChromeStatic(row.spec.help, classes="setting-help")
            if row.spec.kind in ("choice", "bool"):
                # prevent() guards a future Changed-on-seed; on textual 8.2.8
                # constructor values emit nothing, so the mutant is equivalent.
                with self.prevent(Select.Changed):  # pragma: no mutate
                    yield Select(
                        [(choice, choice) for choice in row.spec.choices],
                        value=format_setting_value(row.value),
                        id=editor_id,
                        allow_blank=False,
                    )
            else:
                # Same defensive guard — unseeded Inputs emit no Changed.
                with self.prevent(Input.Changed):  # pragma: no mutate
                    yield Input(
                        format_setting_value(row.value),
                        type="number",
                        validators=[Number(minimum=row.spec.lo, maximum=row.spec.hi)],
                        id=editor_id,
                    )

    def on_mount(self) -> None:
        """The window title follows the pushed screen."""
        self.app.update_terminal_title()

    # -- writes ----------------------------------------------------------------

    @on(Input.Submitted)
    def _submitted(self, event: Input.Submitted) -> None:
        self._write_editor(event.input)

    @on(Input.Blurred)
    def _blurred(self, event: Input.Blurred) -> None:
        self._write_editor(event.input)

    @on(Select.Changed)
    def _choice_made(self, event: Select.Changed) -> None:
        """A pick writes immediately; a rejected one reverts the select."""
        spec = self._specs.get(event.select.id or "")
        if spec is None or event.value is Select.BLANK:
            return
        if self.app.apply_setting(spec, str(event.value)):
            return
        # prevent() stops the revert echoing back through this handler.
        with self.prevent(Select.Changed):  # pragma: no mutate
            select = cast(Select[str], event.select)  # schema strings
            select.value = self._effective(spec)

    def _write_editor(self, editor: Input) -> None:
        """Persist the typed value; a rejected edit notifies and reverts."""
        # Any sentinel misses the dict identically — ids are always set here.
        spec = self._specs.get(editor.id or "")  # pragma: no mutate
        if spec is None:
            return
        if self.app.apply_setting(spec, editor.value):
            return
        # revert under prevent() — a Changed echo would loop through here
        with self.prevent(Input.Changed):  # pragma: no mutate
            editor.value = self._effective(spec)

    def _effective(self, spec: SettingSpec) -> str:
        """The stored value for *spec*'s key, spelled like the seed."""
        row = next(r for r in self.app.settings_rows() if r.spec is spec)
        return format_setting_value(row.value)
