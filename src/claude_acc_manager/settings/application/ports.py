"""Ports for the settings component — the boundary use cases orchestrate."""

from pathlib import Path
from typing import Protocol

from claude_acc_manager.settings.domain.settings_spec import (
    AutoSettings,
    EffectiveSetting,
    SettingSpec,
)


class SettingsPort(Protocol):
    """Persistence boundary for ``settings.json``.

    ``load`` is forgiving (hand-edited garbage degrades to defaults); the
    write methods carry already-validated values and raise ``ValueError``
    when the file is too torn to safely read-modify-write.
    """

    def load(self) -> AutoSettings:
        """The effective autoswitch settings — missing/corrupt file → defaults."""
        ...

    def set_value(self, spec: SettingSpec, value: float | str) -> None:
        """Persist *value* under *spec*'s key, preserving unknown keys/sections."""
        ...

    def unset_value(self, spec: SettingSpec) -> bool:
        """Remove *spec*'s key; ``False`` when it wasn't set (no write)."""
        ...

    def effective(self) -> tuple[EffectiveSetting, ...]:
        """One row per spec key, in spec order, flagging explicitly-set keys."""
        ...

    @property
    def path(self) -> Path:
        """The settings file path (``cam config path``)."""
        ...
