"""Account identity value objects.

mutmut 3.7.0 skips decorated classes entirely (file_mutation.py: decorators
can have side effects in trampoline copies), so all validation logic lives in
the module-level normalized_account_name() and stays mutation-visible; the
dataclass shell only wires it into construction.
"""

import re
from dataclasses import dataclass

# Evidence for the accepted charset: claude-swap models.py normalize_alias
# (letters/digits/./-/_ — lowercase, no leading "-", never empty) merged with
# ai-usagebar config.rs validate_account_label (rejects path separators, ":",
# control chars, "." and ".."). The purely-numeric alias rule of claude-swap
# is dropped: our store has no numeric slot identifiers to collide with.
_NAME_PATTERN = re.compile(r"^[a-z0-9_.-]+$")


def normalized_account_name(raw: str) -> str:
    """Validate and normalize an account name (stripped, lowercase).

    Doubles as the account's directory name under the store's accounts/ tree,
    so path-unsafe names are rejected.

    Example:
        normalized_account_name(" Work ") == "work"
    """
    normalized = raw.strip().lower()
    if not normalized:
        raise ValueError(f"account name cannot be empty (got {raw!r})")
    if normalized.startswith("-"):
        raise ValueError(
            f"account name {normalized!r} cannot start with '-' (argparse would read it as a flag)"
        )
    if normalized in (".", ".."):
        raise ValueError(f"account name {normalized!r} is reserved (path safety)")
    if not _NAME_PATTERN.match(normalized):
        raise ValueError(
            f"account name {normalized!r} may only contain letters, digits, '-', '_' and '.'"
        )
    return normalized


@dataclass(frozen=True)
class AccountName:
    """A validated account name, normalized to stripped lowercase.

    Example:
        AccountName("Work") == AccountName("work")  # both normalize to "work"
    """

    value: str

    def __post_init__(self) -> None:
        """Normalize on construction (frozen instance, so set once here)."""
        object.__setattr__(self, "value", normalized_account_name(self.value))

    def __str__(self) -> str:
        """Print the normalized value, not the dataclass repr."""
        return self.value
