"""In-memory SettingsPort fake for hermetic use-case tests."""

from pathlib import Path

from claude_acc_manager.settings.application.ports import SettingsPort
from claude_acc_manager.settings.domain.settings_spec import (
    SETTING_SPECS,
    AutoSettings,
    EffectiveSetting,
    PrivacySettings,
    SettingSpec,
    clamped_auto_settings,
    clamped_privacy_settings,
    setting_spec,
)


class InMemorySettings(SettingsPort):
    """SettingsPort backed by a dict — same forgiving-load contract."""

    def __init__(self, store_root: Path) -> None:
        """Start with no stored keys under *store_root*."""
        self._store_root = store_root
        self._values: dict[str, float | str | bool] = {}

    def _section_values(self, section: str) -> dict[str, object]:
        """The stored values of one section, keyed like the file shape."""
        return {
            spec.json_key: self._values[spec.dotted]
            for spec in SETTING_SPECS.values()
            if spec.section == section and spec.dotted in self._values
        }

    def load(self) -> AutoSettings:
        """Effective autoswitch settings: stored values over the defaults."""
        return clamped_auto_settings(self._section_values("autoswitch"))

    def load_privacy(self) -> PrivacySettings:
        """Effective privacy settings: stored values over the defaults."""
        return clamped_privacy_settings(self._section_values("privacy"))

    def set_value(self, spec: SettingSpec, value: float | str | bool) -> None:
        """Record *value* under *spec*'s dotted key."""
        self._values[spec.dotted] = value

    def unset_value(self, spec: SettingSpec) -> bool:
        """Drop the key; ``False`` when it wasn't set."""
        return self._values.pop(spec.dotted, None) is not None

    def effective(self) -> tuple[EffectiveSetting, ...]:
        """One row per spec key in spec order."""
        loaded: dict[str, AutoSettings | PrivacySettings] = {
            "autoswitch": self.load(),
            "privacy": self.load_privacy(),
        }
        return tuple(
            EffectiveSetting(
                spec=spec,
                value=getattr(loaded[spec.section], spec.field),
                is_set=spec.dotted in self._values,
            )
            for spec in SETTING_SPECS.values()
        )

    @property
    def path(self) -> Path:
        """The settings file path the fake stands in for."""
        return self._store_root / "settings.json"


def emails_visible_settings(store_root: Path) -> InMemorySettings:
    """An InMemorySettings pre-seeded ``privacy.redactEmails=false``.

    Tests asserting the email-bearing text pass this to the app/CLI wiring —
    the real load path (store → port → settings use case) stays exercised.
    """
    settings = InMemorySettings(store_root)
    settings.set_value(setting_spec("privacy.redactEmails"), False)
    return settings
