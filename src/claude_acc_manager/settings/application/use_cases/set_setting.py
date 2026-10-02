"""SetSetting use case — strictly-validated write to ``settings.json``."""

from claude_acc_manager.settings.application.ports import SettingsPort
from claude_acc_manager.settings.domain.settings_spec import (
    parse_setting_value,
    setting_spec,
)


class SetSetting:
    """Validate *raw_value* against the key's spec, then persist it.

    Example:
        >>> value = SetSetting(port).execute("autoswitch.threshold", "80")
        >>> value
        80.0
    """

    def __init__(self, settings: SettingsPort) -> None:
        """Inject the settings persistence port."""
        self._settings = settings

    def execute(self, dotted_key: str, raw_value: str) -> float | str:
        """Strict parse then write; returns the stored (typed) value."""
        spec = setting_spec(dotted_key)
        value = parse_setting_value(spec, raw_value)
        self._settings.set_value(spec, value)
        return value
