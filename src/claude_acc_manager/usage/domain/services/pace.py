"""Weekly usage pace — the "(ahead)" marker on a 7-day window.

A weekly window is "ahead of pace" when the account has used more of it than
the fraction of its reset cycle that has elapsed — e.g. 40% used at the
20%-through-the-week mark. Weekly windows only (``seven_day`` and ``scoped``
per-model windows): the 5h window resets too fast for pace to mean anything
(the ~3-minute poll floor is a large fraction of a 5h window but negligible
against a week). Elapsed is measured against the entry's ``fetched_at_s``,
so a last-good snapshot is evaluated at the clock it was measured at.

Example:
    compute_pace(window, fetched_at_s=1700000000.0)
"""

from dataclasses import dataclass

from claude_acc_manager.usage.domain.services.poll_policy import parse_reset_epoch
from claude_acc_manager.usage.domain.usage_snapshot import UsageWindow

WEEKLY_PERIOD_S = 7 * 86400.0

# Suppress the marker for this long after a weekly reset. Right after reset,
# elapsed is tiny so expected_pct is near zero and almost any usage reads as
# "far ahead" — a false positive, not a genuine pace warning.
SUPPRESS_AFTER_RESET_S = 24 * 3600.0

# Minimum (actual - expected) percentage-point gap before showing a marker.
# Below this, "ahead of pace" is within normal usage variance and would just
# add noise. A flat gap also means the marker cannot fire once expected
# passes (100 - threshold) — the last ~day of the week — since pct tops out
# at 100. Deliberate: by then the percentage itself tells the story.
AHEAD_THRESHOLD_PCT = 15.0


@dataclass(frozen=True)
class PaceResult:
    """One weekly window's pace at the moment its snapshot was fetched."""

    expected_pct: float  # % of the week's budget "on schedule" usage would be at
    actual_pct: float  # the window's actual pct
    elapsed_s: float  # time since this window's current cycle started
    period_s: float  # the window's full cycle length (e.g. 7 days)
    ahead: bool  # actual_pct - expected_pct >= the "meaningfully ahead" threshold


def compute_pace(
    window: UsageWindow | None,
    *,
    fetched_at_s: float | None,
    period_s: float = WEEKLY_PERIOD_S,
    suppress_after_reset_s: float = SUPPRESS_AFTER_RESET_S,
    ahead_threshold_pct: float = AHEAD_THRESHOLD_PCT,
) -> PaceResult | None:
    """Pace for one weekly usage window, or None when pace isn't meaningful.

    ``resets_at`` is the *next* reset, not the current window's start — the
    only timestamp the usage API provides. The current window's start is
    derived by folding ``resets_at - fetched_at_s`` by whole ``period_s``
    increments, correct however many cycles stale the stored timestamp is.
    ``expected_pct`` needs no 100-cap: elapsed is strictly inside
    ``[0, period_s)`` (a ``remaining`` of exactly 0 folds to elapsed 0).

    Returns None when the window or its reset is missing/unparseable, or
    elapsed time is inside ``suppress_after_reset_s``.
    """
    if window is None or fetched_at_s is None:
        return None
    next_reset = parse_reset_epoch(window.resets_at)
    if next_reset is None:
        return None

    remaining = (next_reset - fetched_at_s) % period_s
    elapsed = 0.0 if remaining == 0 else period_s - remaining

    if elapsed < suppress_after_reset_s:
        return None

    expected_pct = elapsed / period_s * 100.0
    return PaceResult(
        expected_pct=expected_pct,
        actual_pct=window.pct,
        elapsed_s=elapsed,
        period_s=period_s,
        ahead=(window.pct - expected_pct) >= ahead_threshold_pct,
    )
