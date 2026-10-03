"""Pure switch-target selection — rotation, next-available, and best.

The selection contract over a caller-resolved view: names in registry order,
an anchor (live-resolved account, else the recorded pointer), the
live-resolved *current*, and per-name eligibility + headroom sets. Nothing
here touches I/O; the use case feeds it.

Semantics worth naming, because they are the safety contract:

- ``best`` only ever lands on a *strictly* better account; ties stay put.
- Unknown usage is never treated as exhausted — an unmeasurable current or an
  unverifiable comparison stays put (``usage-unavailable``), and an unmeasured
  ``next-available`` candidate is not skipped.
- Disabled, quarantined, and credential-less accounts are out of every
  automatic pick but stay valid explicit ``cam switch <name>`` targets.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

SwitchStrategy = Literal["rotation", "next-available", "best"]

SwitchOutcome = Literal[
    "switch",
    "already-best",
    "candidates-exhausted",
    "usage-unavailable",
    "no-valid-target",
]

SkipReason = Literal["disabled", "quarantined", "no-credentials", "at-limit"]


@dataclass(frozen=True)
class SkippedCandidate:
    """One rotation candidate held out, with the reason."""

    name: str
    reason: SkipReason


@dataclass(frozen=True)
class SwitchSelection:
    """The verdict: a target name, or ``None`` plus the reason to stay."""

    target: str | None
    outcome: SwitchOutcome
    skipped: tuple[SkippedCandidate, ...] = ()


def _ineligible_reason(
    name: str,
    disabled: Collection[str],
    quarantined: Collection[str],
    has_credentials: Collection[str] | None,
) -> SkipReason | None:
    """First skip reason for *name* in walk order, or None when eligible."""
    if name in disabled:
        return "disabled"
    if name in quarantined:
        return "quarantined"
    if has_credentials is not None and name not in has_credentials:
        return "no-credentials"
    return None


def _rotate(
    names: Sequence[str],
    anchor: str | None,
    strategy: SwitchStrategy,
    disabled: Collection[str],
    quarantined: Collection[str],
    has_credentials: Collection[str] | None,
    headroom: Mapping[str, float | None],
) -> SwitchSelection:
    """Walk registry order past the anchor, skipping ineligible candidates."""
    index = names.index(anchor) if anchor in names else 0
    skipped: list[SkippedCandidate] = []
    for offset in range(1, len(names)):
        candidate = names[(index + offset) % len(names)]
        reason = _ineligible_reason(candidate, disabled, quarantined, has_credentials)
        if reason is not None:
            skipped.append(SkippedCandidate(candidate, reason))
            continue
        candidate_headroom = headroom.get(candidate)
        if (
            strategy == "next-available"
            and candidate_headroom is not None
            and candidate_headroom <= 0
        ):
            skipped.append(SkippedCandidate(candidate, "at-limit"))
            continue
        return SwitchSelection(candidate, "switch", tuple(skipped))
    # An exhausted candidate earns a different stay-reason than a merely
    # ineligible one — "try again later" vs "nothing valid exists".
    if any(note.reason == "at-limit" for note in skipped):
        return SwitchSelection(None, "candidates-exhausted", tuple(skipped))
    return SwitchSelection(None, "no-valid-target", tuple(skipped))


def _eligible_others(
    names: Sequence[str],
    current: str | None,
    disabled: Collection[str],
    quarantined: Collection[str],
    has_credentials: Collection[str] | None,
) -> list[str]:
    """Every account that could be picked, in registry order."""
    return [
        name
        for name in names
        if name != current
        and _ineligible_reason(name, disabled, quarantined, has_credentials) is None
    ]


def _best_among(
    others: Sequence[str],
    current_headroom: float,
    headroom: Mapping[str, float | None],
) -> SwitchSelection:
    """Compare measured candidates against the current account's headroom."""
    # Only measured candidates can beat the current account; the walrus keeps
    # this list narrowed to float (never-None) so max() types cleanly.
    scored = [(h, name) for name in others if (h := headroom.get(name)) is not None]
    if not scored:
        return SwitchSelection(None, "usage-unavailable")

    best_headroom, best_name = max(scored, key=lambda t: t[0])
    if best_headroom > current_headroom:
        return SwitchSelection(best_name, "switch")
    if len(scored) != len(others):
        # Current beats every measured candidate, but an unmeasured one could
        # still be better — neither "best" nor "exhausted" is provable.
        return SwitchSelection(None, "usage-unavailable")
    if current_headroom <= 0:
        return SwitchSelection(None, "candidates-exhausted")
    return SwitchSelection(None, "already-best")


def _select_best(
    names: Sequence[str],
    current: str | None,
    disabled: Collection[str],
    quarantined: Collection[str],
    has_credentials: Collection[str] | None,
    headroom: Mapping[str, float | None],
) -> SwitchSelection:
    """Provably better or stay — see the module docstring's safety contract."""
    others = _eligible_others(names, current, disabled, quarantined, has_credentials)
    if not others:
        skipped = tuple(
            SkippedCandidate(name, reason)
            for name in names
            if name != current
            and (reason := _ineligible_reason(name, disabled, quarantined, has_credentials))
            is not None
        )
        return SwitchSelection(None, "no-valid-target", skipped)

    # headroom is Mapping[str, ...] — a None key is outside the contract, so
    # the `or True` mutant's `headroom.get(None)` still returns None.
    current_headroom = headroom.get(current) if current is not None else None  # pragma: no mutate
    if current_headroom is None:
        # Can't measure where the user is → can't prove any target is better.
        return SwitchSelection(None, "usage-unavailable")
    return _best_among(others, current_headroom, headroom)


def select_switch_target(
    names: Sequence[str],
    *,
    anchor: str | None,
    current: str | None,
    strategy: SwitchStrategy,
    disabled: Collection[str] = (),
    quarantined: Collection[str] = (),
    has_credentials: Collection[str] | None = None,
    headroom: Mapping[str, float | None] | None = None,
) -> SwitchSelection:
    """Pick the account ``cam switch`` should land on, or why to stay.

    *names* is registry order. *anchor* is the rotation pivot: the
    live-resolved account when one is live, else the recorded pointer (an
    unresolved anchor falls back to index 0 — the first account is treated as
    current, matching the reference's fallback). *current* is the
    live-resolved account only — ``best``'s comparison baseline; an unmanaged
    live login passes ``None`` and gets ``usage-unavailable``. *has_credentials*
    is the set of names whose account dir still holds a credential (``None``
    = all present). *headroom* maps an account name to its measured headroom
    percent; absent keys mean unknown, never exhausted.

    Example:
        >>> select_switch_target(("a", "b"), anchor="a", current="a",
        ...                      strategy="best", headroom={"a": 10.0, "b": 80.0})
        SwitchSelection(target='b', outcome='switch', skipped=())
    """
    usage = headroom or {}
    if strategy == "best":
        return _select_best(names, current, disabled, quarantined, has_credentials, usage)
    return _rotate(names, anchor, strategy, disabled, quarantined, has_credentials, usage)
