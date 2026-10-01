"""Parsed shape of the Anthropic ``GET /api/oauth/usage`` response (docs/architecture.md §3).

Evidence: claude-swap ``oauth.py`` ``build_usage_result`` reads only
``five_hour``, ``seven_day``, and ``limits`` at the top level; ai-usagebar
``src/anthropic/types.rs`` marks every field ``#[serde(default)]`` because
"the shape varies across plan tiers and over time" — proven by its own test
fixture smuggling an unmodeled ``"tangelo"`` key past the parser. Per-model
weekly windows (e.g. "Fable") live only in the newer ``limits[]`` array, keyed
by *having* a ``scope.model.display_name`` — both references match on that
shape alone, never on ``limits[].kind``, so this parser does the same. A
missing or malformed piece is dropped individually, never a parse failure
(docs/architecture.md §11: "missing window → None, not crash"). ``extra_usage`` (pay-as-you-go
spend) is deliberately not modeled here: no milestone up to and including the
switch strategies consumes it (claude-swap's own headroom logic excludes it
as "a separate axis"), so parsing it now would be a speculative field with no
caller — it can be added, evidenced by a real consumer, whenever one exists.

mutmut 3.7.0 skips decorated callables, so the logic is a module-level
function and the dataclasses are its immutable shell (same rule as
accounts/domain/oauth_identity.py).

Example:
    snapshot = usage_snapshot_from_response(json.loads(usage_response_body))
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast


@dataclass(frozen=True)
class UsageWindow:
    """One utilization window (the 5-hour or 7-day rolling limit).

    Example:
        UsageWindow(pct=62.0, resets_at="2026-05-23T13:30:00Z")
    """

    pct: float
    resets_at: str | None


@dataclass(frozen=True)
class ScopedWindow:
    """A per-model weekly window from the ``limits[]`` array (e.g. "Fable").

    Example:
        ScopedWindow(name="Fable", pct=84.0, resets_at="2026-05-27T13:00:00Z")
    """

    name: str
    pct: float
    resets_at: str | None


@dataclass(frozen=True)
class UsageSnapshot:
    """Everything this tool reads out of one ``oauth/usage`` response.

    Example:
        UsageSnapshot(UsageWindow(62.0, "2026-05-23T13:30:00Z"), None, ())
    """

    five_hour: UsageWindow | None
    seven_day: UsageWindow | None
    scoped: tuple[ScopedWindow, ...]


def _numeric(value: object) -> float | None:
    """Return *value* as a float, or None — bool is an int subclass, excluded."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _as_object_map(value: object) -> Mapping[str, object] | None:
    """Narrow *value* to a string-keyed JSON object, or None.

    cast() is a runtime no-op — its type argument is type-checker-only, so
    mutants of it are equivalent by construction (same reason
    accounts/domain/oauth_identity.py and file_account_store carry this
    pragma).
    """
    if not isinstance(value, Mapping):
        return None
    return cast("Mapping[str, object]", value)  # pragma: no mutate


def _window(value: object) -> UsageWindow | None:
    """Parse one ``{"utilization": ..., "resets_at": ...}`` window, or None."""
    window = _as_object_map(value)
    if window is None:
        return None
    pct = _numeric(window.get("utilization"))
    if pct is None:
        return None
    return UsageWindow(pct=pct, resets_at=_optional_str(window.get("resets_at")))


def _scoped_window(entry: object) -> ScopedWindow | None:
    """Parse one ``limits[]`` entry into a ScopedWindow, or None when unnamed."""
    limit = _as_object_map(entry)
    if limit is None:
        return None
    scope = _as_object_map(limit.get("scope"))
    model = _as_object_map(scope.get("model")) if scope is not None else None
    name = model.get("display_name") if model is not None else None
    pct = _numeric(limit.get("percent"))
    if not isinstance(name, str) or not name or pct is None:
        return None
    return ScopedWindow(name=name, pct=pct, resets_at=_optional_str(limit.get("resets_at")))


def _scoped_windows(value: object) -> tuple[ScopedWindow, ...]:
    """Every named model-scoped weekly window in a ``limits[]`` array."""
    if not isinstance(value, list):
        return ()
    entries = cast("list[object]", value)  # pragma: no mutate — see _as_object_map
    parsed = (_scoped_window(entry) for entry in entries)
    return tuple(window for window in parsed if window is not None)


def usage_snapshot_from_response(data: Mapping[str, object]) -> UsageSnapshot:
    """Parse a loaded ``GET /api/oauth/usage`` JSON body.

    Every piece is independently optional: a missing or malformed window or
    ``limits[]`` entry is dropped, never a parse failure.

    Example:
        usage_snapshot_from_response({"five_hour": {"utilization": 62.0}})
    """
    return UsageSnapshot(
        five_hour=_window(data.get("five_hour")),
        seven_day=_window(data.get("seven_day")),
        scoped=_scoped_windows(data.get("limits")),
    )
