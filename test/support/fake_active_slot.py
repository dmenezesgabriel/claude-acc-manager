"""ActiveSlotPort fake holding the live credential + config in memory."""

from pathlib import Path

from claude_acc_manager.accounts.application.ports import ActiveSlotPort


class FakeActiveSlot(ActiveSlotPort):
    """In-memory stand-in for Claude Code's live credential + config slot."""

    def __init__(
        self,
        *,
        credentials: dict[str, object] | None = None,
        config: dict[str, object] | None = None,
    ) -> None:
        """Seed the slot's starting credentials and config (``None`` = absent)."""
        self._credentials = credentials
        self._config = config

    def read_credentials(self) -> dict[str, object] | None:
        """The current credentials, or ``None`` when absent."""
        return self._credentials

    def write_credentials(self, credentials: dict[str, object]) -> None:
        """Replace the credentials."""
        self._credentials = credentials

    def read_config(self) -> dict[str, object] | None:
        """The current config, or ``None`` when absent."""
        return self._config

    def write_config(self, config: dict[str, object]) -> None:
        """Replace the config."""
        self._config = config

    def splice_config_oauth_account(self, oauth_account: dict[str, object]) -> None:
        """Set only the ``oauthAccount`` key, creating the config when absent."""
        self._config = {**(self._config or {}), "oauthAccount": oauth_account}

    def salvage_torn_config(self) -> Path | None:
        """No torn file in memory — always ``None``."""
        return None
