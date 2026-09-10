"""Identity resolved by Anthropic's ``GET /api/oauth/profile`` identity oracle.

Evidence: claude-swap ``oauth.py`` ``fetch_oauth_profile`` (its own docstring:
"a response counts as resolved only when it carries a non-empty string
account.uuid ... email/organizationUuid are optional"). This is the "usage may
import accounts, never the reverse" boundary in practice (plan §4.1): the M6
switch transaction (in ``accounts``) needs this identity to classify an
unattributable outgoing credential, but the wire call and its shape belong
here, next to the other two Anthropic OAuth calls, so ``accounts`` imports
this type rather than ``usage`` importing ``accounts.domain.oauth_identity``.

Example:
    identity = resolved_identity_from_profile_response(json.loads(profile_body))
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast


@dataclass(frozen=True)
class ResolvedIdentity:
    """The account (and optionally organization) a credential belongs to.

    Example:
        ResolvedIdentity(account_uuid="acc-123", email="a@b.c", organization_uuid=None)
    """

    account_uuid: str
    email: str | None
    organization_uuid: str | None


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _as_object_map(value: object) -> Mapping[str, object] | None:
    """Narrow *value* to a string-keyed JSON object, or None.

    cast() is a runtime no-op — its type argument is type-checker-only, so
    mutants of it are equivalent by construction (same reason
    accounts/domain/oauth_identity.py carries this pragma).
    """
    if not isinstance(value, Mapping):
        return None
    return cast("Mapping[str, object]", value)  # pragma: no mutate


def resolved_identity_from_profile_response(data: Mapping[str, object]) -> ResolvedIdentity | None:
    """Parse a loaded ``GET /api/oauth/profile`` JSON body.

    Returns ``None`` for anything short of a usable ``account.uuid`` — a
    missing/non-object ``account``, or a missing/blank/non-string ``uuid`` —
    matching claude-swap's fail-open contract (the identity oracle is
    advisory; callers proceed on ``None`` rather than treating it as an
    error). ``email`` and ``organization.uuid`` are optional.

    Example:
        resolved_identity_from_profile_response({"account": {"uuid": "acc-123"}})
    """
    account = _as_object_map(data.get("account"))
    if account is None:
        return None
    uuid = account.get("uuid")
    if not isinstance(uuid, str) or not uuid.strip():
        return None
    organization = _as_object_map(data.get("organization"))
    org_uuid = organization.get("uuid") if organization is not None else None
    return ResolvedIdentity(
        account_uuid=uuid.strip(),
        email=_optional_str(account.get("email")),
        organization_uuid=_optional_str(org_uuid),
    )
