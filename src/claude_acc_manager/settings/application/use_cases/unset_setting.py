"""UnsetSetting use case — remove a key so the default governs again."""

from claude_acc_manager.settings.application.ports import SettingsPort
from claude_acc_manager.settings.domain.settings_spec import setting_spec


class UnsetSetting:
    """Remove *dotted_key* from ``settings.json``; ``False`` when not set."""

    def __init__(self, settings: SettingsPort) -> None:
        """Inject the settings persistence port."""
        self._settings = settings

    def execute(self, dotted_key: str) -> bool:
        """Delete the key; ``True`` when a write actually removed something."""
        return self._settings.unset_value(setting_spec(dotted_key))
