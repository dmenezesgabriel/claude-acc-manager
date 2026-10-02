"""In-memory SettingsPort fake for hermetic use-case tests."""

from pathlib import Path

from claude_acc_manager.settings.application.ports import SettingsPort
from claude_acc_manager.settings.domain.settings_spec import (
    SETTING_SPECS,
    AutoSettings,
    EffectiveSetting,
    SettingSpec,
    strict_override,
)


class InMemorySettings(SettingsPort):
    """SettingsPort backed by a dict — same forgiving-load contract."""

    def __init__(self, store_root: Path) -> None:
        """Start with no stored keys under *store_root*."""
        self._store_root = store_root
        self._values: dict[str, float | str] = {}

    def load(self) -> AutoSettings:
        """Effective settings: stored values over the defaults."""
        overrides = {
            spec.field: self._values[spec.dotted]
            for spec in SETTING_SPECS.values()
            if spec.dotted in self._values
        }
        return strict_override(AutoSettings(), overrides)

    def set_value(self, spec: SettingSpec, value: float | str) -> None:
        """Record *value* under *spec*'s dotted key."""
        self._values[spec.dotted] = value

    def unset_value(self, spec: SettingSpec) -> bool:
        """Drop the key; ``False`` when it wasn't set."""
        return self._values.pop(spec.dotted, None) is not None

    def effective(self) -> tuple[EffectiveSetting, ...]:
        """One row per spec key in spec order."""
        settings = self.load()
        return tuple(
            EffectiveSetting(
                spec=spec,
                value=getattr(settings, spec.field),
                is_set=spec.dotted in self._values,
            )
            for spec in SETTING_SPECS.values()
        )

    @property
    def path(self) -> Path:
        """The settings file path the fake stands in for."""
        return self._store_root / "settings.json"
