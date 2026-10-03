"""Credential-file field ownership, lineage fingerprinting, and the wiped check.

Credential JSON has two ownership classes: machine-shared keys (MCP OAuth
state, plugin secrets — config-global, copied into every login) and slot-owned
keys (claudeAiOauth, trustedDeviceToken, unknown siblings). Activating an
account must compose the stored blob with the *machine's* shared generation,
not resurrect the generation frozen at capture.

cam never refreshes the active account's credential file (ADR-0009), so
there is no "credentials changed while activating" consume pass — the
compose happens once, when the blob is staged into the live slot.
"""

import hashlib
import json
from collections.abc import Mapping
from typing import cast

SHARED_CREDENTIAL_KEYS = frozenset(
    {
        "mcpOAuth",
        "mcpOAuthClientConfig",
        "mcpXaaIdp",
        "mcpXaaIdpConfig",
        "pluginSecrets",
    }
)


def shared_credential_fields(credentials: Mapping[str, object] | None) -> dict[str, object] | None:
    """Return the machine-shared keys of a parsed credential object.

    ``None`` means no credential object exists at all — distinct from ``{}``,
    which means "this machine's credential holds no shared keys" and wipes the
    activated blob's stale copies.

    Example:
        >>> shared_credential_fields({"mcpOAuth": {"a": 1}, "other": 2})
        {'mcpOAuth': {'a': 1}}
    """
    if credentials is None:
        return None
    return {key: credentials[key] for key in SHARED_CREDENTIAL_KEYS if key in credentials}


def compose_activation_credentials(
    target: Mapping[str, object], live: Mapping[str, object] | None
) -> dict[str, object]:
    """Build the blob written to the live slot when activating *target*.

    Every non-shared key is slot-owned and comes from *target*; shared keys
    come from *live* — including their absence, which strips stale copies.
    ``live is None`` activates the stored blob verbatim.

    Example:
        >>> compose_activation_credentials(
        ...     {"claudeAiOauth": {"a": "t"}, "mcpOAuth": {"old": 1}},
        ...     {"mcpOAuth": {"new": 2}},
        ... )
        {'claudeAiOauth': {'a': 't'}, 'mcpOAuth': {'new': 2}}
    """
    live_shared = shared_credential_fields(live)
    if live_shared is None:
        return dict(target)
    composed = {k: v for k, v in target.items() if k not in SHARED_CREDENTIAL_KEYS}
    composed.update(live_shared)
    return composed


def refresh_token_fingerprint(credentials: Mapping[str, object]) -> str | None:
    """Fingerprint the credential's refresh-token lineage.

    The refresh token is the lineage: its sha256 is identical across access-
    token rotations, so a fingerprint survives the refresh cycle that made the
    pre-switch comparison lie. With no usable refresh token the identity is
    the content itself (``sha256-json:`` of the canonical dict).

    Example:
        >>> refresh_token_fingerprint({"claudeAiOauth": {"refreshToken": "rt"}})
        'sha256:...'
    """
    oauth = credentials.get("claudeAiOauth")
    # cast() is a runtime no-op; the isinstance already proved the shape.
    # Mutants of its type argument are equivalent by construction — same
    # pragma as oauth_identity_from_config's Mapping narrow.
    block: Mapping[str, object] = {}
    if isinstance(oauth, Mapping):
        block = cast("Mapping[str, object]", oauth)  # pragma: no mutate
    rt = block.get("refreshToken")
    if isinstance(rt, str) and rt:
        return "sha256:" + hashlib.sha256(rt.encode()).hexdigest()
    digest = hashlib.sha256(json.dumps(dict(credentials), sort_keys=True).encode()).hexdigest()
    return "sha256-json:" + digest


def oauth_tokens_wiped(credentials: Mapping[str, object]) -> bool:
    """True when claude code emptied both token fields of the OAuth blob.

    After an ``invalid_grant`` response claude code wipes ``accessToken`` and
    ``refreshToken`` in place, leaving ``expiresAt``/``scopes`` intact — a
    credential that *looks* structured but carries no lineage worth capturing.
    Blobs that are not OAuth credentials (missing or torn ``claudeAiOauth``)
    are not "wiped" — preserving foreign bytes is always safe.

    Example:
        >>> oauth_tokens_wiped({"claudeAiOauth": {"accessToken": "", "refreshToken": ""}})
        True
    """
    oauth = credentials.get("claudeAiOauth")
    if not isinstance(oauth, Mapping):
        return False
    block = cast("Mapping[str, object]", oauth)  # pragma: no mutate
    at, rt = block.get("accessToken"), block.get("refreshToken")
    present = [t for t in (at, rt) if isinstance(t, str) and t]
    return not present
