"""In-memory CredentialStorePort fake for hermetic use-case tests."""

from claude_acc_manager.usage.application.ports import CredentialStorePort
from claude_acc_manager.usage.domain.oauth_credential import StoredOAuthCredential


class FakeCredentialStore(CredentialStorePort):
    """CredentialStorePort backed by a dict keyed on account name string.

    Records every rotation it was asked to persist so tests can assert the
    exact tokens a refresh wrote back.
    """

    def __init__(self, *, credentials: dict[str, StoredOAuthCredential] | None = None) -> None:
        """Seed the store with *credentials* (defaults to none)."""
        self._credentials: dict[str, StoredOAuthCredential] = dict(credentials or {})
        self.rotations: list[tuple[str, str, str, float]] = []

    def read(self, account_key: str) -> StoredOAuthCredential | None:
        """The account's stored credential, or None when unknown."""
        return self._credentials.get(account_key)

    def persist_rotation(
        self, account_key: str, access_token: str, refresh_token: str, expires_at_ms: float
    ) -> None:
        """Record the rotation and update the stored credential."""
        self.rotations.append((account_key, access_token, refresh_token, expires_at_ms))
        self._credentials[account_key] = StoredOAuthCredential(
            access_token=access_token, refresh_token=refresh_token, expires_at_ms=expires_at_ms
        )
