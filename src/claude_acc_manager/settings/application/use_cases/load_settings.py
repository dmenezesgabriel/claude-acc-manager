"""LoadSettings use case — the forgiving read every autoswitch consumer shares."""

from claude_acc_manager.settings.application.ports import SettingsPort
from claude_acc_manager.settings.domain.settings_spec import AutoSettings


class LoadSettings:
    """Return the effective autoswitch settings (defaults merged over the file)."""

    def __init__(self, settings: SettingsPort) -> None:
        """Inject the settings persistence port."""
        self._settings = settings

    def execute(self) -> AutoSettings:
        """Forgiving load: a missing/corrupt file yields clamped defaults."""
        return self._settings.load()
