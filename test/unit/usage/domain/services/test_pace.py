"""Unit tests for usage.domain.services.pace."""

from datetime import UTC, datetime

from claude_acc_manager.usage.domain.services.pace import (
    AHEAD_THRESHOLD_PCT,
    SUPPRESS_AFTER_RESET_S,
    WEEKLY_PERIOD_S,
    PaceResult,
    compute_pace,
)
from claude_acc_manager.usage.domain.usage_snapshot import UsageWindow

FETCHED_AT = 1_000_000.0


def _iso(epoch_s: float) -> str:
    return datetime.fromtimestamp(epoch_s, tz=UTC).isoformat().replace("+00:00", "Z")


def _window_with_reset_in(seconds: float, pct: float = 10.0) -> UsageWindow:
    """A window whose next reset is *seconds* ahead of FETCHED_AT."""
    return UsageWindow(pct=pct, resets_at=_iso(FETCHED_AT + seconds))


class TestUncomputableInputs:
    def test_no_window_is_none(self):
        assert compute_pace(None, fetched_at_s=FETCHED_AT) is None

    def test_no_fetch_timestamp_is_none(self):
        window = _window_with_reset_in(WEEKLY_PERIOD_S / 2.0)
        assert compute_pace(window, fetched_at_s=None) is None

    def test_no_reset_is_none(self):
        window = UsageWindow(pct=10.0, resets_at=None)
        assert compute_pace(window, fetched_at_s=FETCHED_AT) is None

    def test_an_unparseable_reset_is_none(self):
        window = UsageWindow(pct=10.0, resets_at="not-a-timestamp")
        assert compute_pace(window, fetched_at_s=FETCHED_AT) is None


class TestSuppression:
    def test_inside_the_suppression_window_is_none(self):
        # elapsed = period - remaining; 1s short of the 24h cutoff
        window = _window_with_reset_in(WEEKLY_PERIOD_S - SUPPRESS_AFTER_RESET_S + 1.0)
        assert compute_pace(window, fetched_at_s=FETCHED_AT) is None

    def test_at_the_suppression_boundary_is_computed(self):
        # exactly 24h elapsed -> no longer suppressed
        window = _window_with_reset_in(WEEKLY_PERIOD_S - SUPPRESS_AFTER_RESET_S)
        pace = compute_pace(window, fetched_at_s=FETCHED_AT)
        assert pace is not None
        assert pace.elapsed_s == SUPPRESS_AFTER_RESET_S

    def test_a_reset_exactly_at_fetch_is_none(self):
        # remaining == 0 folds to elapsed 0 — a window fetched on its reset
        # instant reads as brand new, not a full cycle old
        window = _window_with_reset_in(0.0)
        assert compute_pace(window, fetched_at_s=FETCHED_AT) is None

    def test_the_reset_instant_reports_zero_elapsed(self):
        # suppression off: the fold still lands at elapsed == 0 exactly, not
        # a stray sliver — anything else would leak into expected_pct
        window = _window_with_reset_in(0.0, pct=80.0)
        pace = compute_pace(window, fetched_at_s=FETCHED_AT, suppress_after_reset_s=0.0)
        assert pace is not None
        assert pace.elapsed_s == 0.0
        assert pace.expected_pct == 0.0
        assert pace.ahead is True


class TestExpectedPct:
    def test_half_a_week_elapsed_is_50_percent_expected(self):
        window = _window_with_reset_in(WEEKLY_PERIOD_S / 2.0)
        pace = compute_pace(window, fetched_at_s=FETCHED_AT)
        assert pace == PaceResult(
            expected_pct=50.0,
            actual_pct=10.0,
            elapsed_s=WEEKLY_PERIOD_S / 2.0,
            period_s=WEEKLY_PERIOD_S,
            ahead=False,
        )

    def test_a_stale_reset_already_in_the_past_still_folds(self):
        # resets_at 2d behind fetched_at (not yet rolled forward): remaining
        # folds to period-2d, so elapsed is 2d — correct however stale the
        # stored timestamp is
        window = _window_with_reset_in(-2.0 * 86400.0)
        pace = compute_pace(window, fetched_at_s=FETCHED_AT)
        assert pace is not None
        assert pace.elapsed_s == 2.0 * 86400.0

    def test_nearly_a_full_cycle_elapsed_is_still_under_100(self):
        # elapsed < period strictly (remaining == 0 folds to elapsed 0), so
        # expected never reaches 100 — no cap needed or wanted. And the
        # marker cannot fire here: pct 100 against expected ~100 is a gap of
        # ~0, far under the 15pp threshold — deliberate, by then the
        # percentage itself tells the story
        window = _window_with_reset_in(1.0, pct=100.0)
        pace = compute_pace(window, fetched_at_s=FETCHED_AT)
        assert pace is not None
        assert pace.expected_pct < 100.0
        assert pace.ahead is False


class TestAheadMarker:
    def test_exactly_at_the_threshold_is_ahead(self):
        # half a week elapsed -> expected 50; 50 + 15 = 65 is the boundary
        window = _window_with_reset_in(WEEKLY_PERIOD_S / 2.0, pct=65.0)
        pace = compute_pace(window, fetched_at_s=FETCHED_AT)
        assert pace is not None
        assert pace.ahead is True

    def test_just_under_the_threshold_is_not_ahead(self):
        window = _window_with_reset_in(WEEKLY_PERIOD_S / 2.0, pct=50.0 + AHEAD_THRESHOLD_PCT - 0.01)
        pace = compute_pace(window, fetched_at_s=FETCHED_AT)
        assert pace is not None
        assert pace.ahead is False

    def test_behind_pace_is_not_ahead(self):
        window = _window_with_reset_in(WEEKLY_PERIOD_S / 2.0, pct=10.0)
        pace = compute_pace(window, fetched_at_s=FETCHED_AT)
        assert pace is not None
        assert pace.ahead is False
