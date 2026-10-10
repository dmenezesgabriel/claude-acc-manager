"""LoadUpdateSettings use case — the updates section's effective values."""

from claude_acc_manager.settings.application.ports import SettingsPort
from claude_acc_manager.settings.domain.settings_spec import UpdateSettings


class LoadUpdateSettings:
    """Read the release-check mode the update surfaces honor.

    Example:
        >>> LoadUpdateSettings(port).execute().mode
        'notify'
    """

    def __init__(self, settings: SettingsPort) -> None:
        """Inject the settings persistence port."""
        self._settings = settings

    def execute(self) -> UpdateSettings:
        """The forgiving load — a missing or corrupt section reads as defaults."""
        return self._settings.load_updates()
