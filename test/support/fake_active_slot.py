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
        live_credentials_path: Path | None = None,
    ) -> None:
        """Seed the slot's starting credentials and config (``None`` = absent)."""
        self._credentials = credentials
        self._config = config
        self._live_path = live_credentials_path or Path("/live/.claude/.credentials.json")

    def credentials_path(self) -> Path:
        """The fake's resolved live path — injectable for the scoped-shell guard."""
        return self._live_path

    def read_credentials(self) -> dict[str, object] | None:
        """The current credentials, or ``None`` when absent."""
        return self._credentials

    def write_credentials(self, credentials: dict[str, object]) -> None:
        """Replace the credentials."""
        self._credentials = credentials

    def delete_credentials(self) -> None:
        """Restore the absent-credentials state."""
        self._credentials = None

    def read_config(self) -> dict[str, object] | None:
        """The current config, or ``None`` when absent."""
        return self._config

    def write_config(self, config: dict[str, object]) -> None:
        """Replace the config."""
        self._config = config

    def delete_config(self) -> None:
        """Restore the absent-config state."""
        self._config = None

    def splice_config_oauth_account(self, oauth_account: dict[str, object]) -> None:
        """Set only the ``oauthAccount`` key, creating the config when absent."""
        self._config = {**(self._config or {}), "oauthAccount": oauth_account}

    def salvage_torn_config(self) -> Path | None:
        """No torn file in memory — always ``None``."""
        return None
