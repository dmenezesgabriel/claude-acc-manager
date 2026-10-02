"""ListSettings use case — every spec key with its effective value."""

from claude_acc_manager.settings.application.ports import SettingsPort
from claude_acc_manager.settings.domain.settings_spec import EffectiveSetting


class ListSettings:
    """Return one ``EffectiveSetting`` row per spec key, in spec order."""

    def __init__(self, settings: SettingsPort) -> None:
        """Inject the settings persistence port."""
        self._settings = settings

    def execute(self) -> tuple[EffectiveSetting, ...]:
        """Rows for ``cam config list``: value, and whether it was set by hand."""
        return self._settings.effective()
