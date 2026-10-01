"""Adapter implementing usage's CredentialStorePort over ``.credentials.json``.

``accounts`` may import ``usage`` (ADR-0010) — this is that one sanctioned
crossing: reading/rotating a captured login's OAuth tokens is fundamentally
an accounts-side file concern (the file lives under the account's own
``CLAUDE_CONFIG_DIR``, resolved via ``AccountStorePort.account_dir``), but
the parsed shape and the port it implements belong to ``usage`` (the fetch
use case's own boundary).

Example:
    credentials = AccountCredentialStore(store)
    credential = credentials.read("work")
"""

from collections.abc import Mapping
from pathlib import Path
from typing import cast

from claude_acc_manager.accounts.application.ports import AccountStorePort
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.shared import fsio
from claude_acc_manager.usage.application.ports import CredentialStorePort
from claude_acc_manager.usage.domain.oauth_credential import (
    StoredOAuthCredential,
    stored_credential_from_claude_ai_oauth,
)

_OAUTH_KEY = "claudeAiOauth"


def _as_object_map(value: object) -> Mapping[str, object] | None:
    """Narrow *value* to a string-keyed JSON object, or None.

    cast() is a runtime no-op — its type argument is type-checker-only, so
    mutants of it are equivalent by construction (same reason
    usage_snapshot.py carries this pragma).
    """
    if not isinstance(value, Mapping):
        return None
    return cast("Mapping[str, object]", value)  # pragma: no mutate


class AccountCredentialStore(CredentialStorePort):
    """CredentialStorePort over ``<account_dir>/.credentials.json``.

    Example:
        AccountCredentialStore(store).persist_rotation("work", at, rt, expires_at_ms)
    """

    def __init__(self, store: AccountStorePort) -> None:
        """Resolve each account's credential file through *store*'s layout."""
        self._store = store

    def _path(self, account_key: str) -> Path:
        return self._store.account_dir(AccountName(account_key)) / ".credentials.json"

    def read(self, account_key: str) -> StoredOAuthCredential | None:
        """The account's stored credential, or None (no file, or no usable token)."""
        path = self._path(account_key)
        if not path.exists():
            return None
        oauth = _as_object_map(fsio.read_json_object(path, "credentials").get(_OAUTH_KEY))
        if oauth is None:
            return None
        return stored_credential_from_claude_ai_oauth(oauth)

    def persist_rotation(
        self, account_key: str, access_token: str, refresh_token: str, expires_at_ms: float
    ) -> None:
        """Replace the account's access token, refresh token, and expiry.

        Every other key — in ``claudeAiOauth`` (``scopes``,
        ``subscriptionType``, ``rateLimitTier``) and at the top level (a
        sibling ``organizationUuid``) — is preserved, atomically.
        """
        path = self._path(account_key)
        credentials: dict[str, object] = (
            dict(fsio.read_json_object(path, "credentials")) if path.exists() else {}
        )
        existing_oauth = _as_object_map(credentials.get(_OAUTH_KEY))
        oauth: dict[str, object] = dict(existing_oauth) if existing_oauth is not None else {}
        oauth["accessToken"] = access_token
        oauth["refreshToken"] = refresh_token
        oauth["expiresAt"] = expires_at_ms
        credentials[_OAUTH_KEY] = oauth
        fsio.atomic_write_json(path, credentials)
