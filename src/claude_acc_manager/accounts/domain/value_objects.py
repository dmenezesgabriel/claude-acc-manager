"""Account identity value objects.

mutmut 3.7.0 skips decorated classes entirely (file_mutation.py: decorators
can have side effects in trampoline copies), so all validation logic lives in
the module-level normalized_account_name() and stays mutation-visible; the
dataclass shell only wires it into construction.
"""

import re
from dataclasses import dataclass

# The name doubles as a directory name under the store and an argv token:
# lowercase letters/digits plus '.', '-', '_' only — no path separators or
# control chars, never "."/"..", never empty, no leading '-'. Purely-numeric
# names stay legal: the store has no numeric slot identifiers to collide with.
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
