"""LoadPrivacySettings use case — the privacy section's effective values."""

from claude_acc_manager.settings.application.ports import SettingsPort
from claude_acc_manager.settings.domain.settings_spec import PrivacySettings


class LoadPrivacySettings:
    """Read the display-privacy knobs the TUI and human CLI output honor.

    Example:
        >>> LoadPrivacySettings(port).execute().redact_emails
        True
    """

    def __init__(self, settings: SettingsPort) -> None:
        """Inject the settings persistence port."""
        self._settings = settings

    def execute(self) -> PrivacySettings:
        """The forgiving load — a missing or corrupt section reads as defaults."""
        return self._settings.load_privacy()
