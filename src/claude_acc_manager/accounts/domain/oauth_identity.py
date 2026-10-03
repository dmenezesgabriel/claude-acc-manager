"""The account identity Claude Code records under ``oauthAccount``.

``~/.claude.json`` carries an ``oauthAccount`` block
(``emailAddress, accountUuid, organizationUuid, organizationName, ...``) that
Claude Code rewrites on every (re-)login (docs/architecture.md §3). Both
``add`` (capturing a fresh login) and ``status`` (classifying the live slot)
need the same three-or-four fields out of that block, so the shape check
lives here once, as a pure parser — mutmut 3.7.0 skips decorated callables,
so the logic is a module-level function and the dataclass is only its
immutable shell (same rule as value_objects.py).

Example:
    identity = oauth_identity_from_config(json_loaded_claude_config)
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast


@dataclass(frozen=True)
class OAuthIdentity:
    """Which account a captured login belongs to.

    ``organization_*`` are optional: a fresh personal login carries no org
    sibling.

    Example:
        OAuthIdentity("user@example.com", "acc-uuid", None, None)
    """

    email: str
    account_uuid: str
    organization_uuid: str | None
    organization_name: str | None


def _require_non_empty_str(field: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"oauthAccount.{field} is {value!r}, expected a non-empty string")
    return value


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def oauth_identity_from_config(config: Mapping[str, object]) -> OAuthIdentity | None:
    """Parse the ``oauthAccount`` block out of a loaded ``~/.claude.json``.

    Returns ``None`` when no account is logged in (the ``oauthAccount`` key is
    absent or ``null``). Raises ``ValueError`` — naming the offending value and
    the expected shape — when the block is present but not an object, or when
    ``emailAddress``/``accountUuid`` are missing or not non-empty strings.

    Example:
        oauth_identity_from_config({"oauthAccount": {"emailAddress": "a@b.c",
                                                    "accountUuid": "u"}})
    """
    oauth_account = config.get("oauthAccount")
    if oauth_account is None:
        return None
    if not isinstance(oauth_account, Mapping):
        raise ValueError(f"oauthAccount is {oauth_account!r}, expected a JSON object")
    # cast() is a runtime no-op — its type argument is type-checker-only, so
    # mutants of it are equivalent by construction (file_account_store._object_map
    # carries the same pragma for the same reason).
    block = cast("Mapping[str, object]", oauth_account)  # pragma: no mutate
    return OAuthIdentity(
        email=_require_non_empty_str("emailAddress", block.get("emailAddress")),
        account_uuid=_require_non_empty_str("accountUuid", block.get("accountUuid")),
        organization_uuid=_optional_str(block.get("organizationUuid")),
        organization_name=_optional_str(block.get("organizationName")),
    )
