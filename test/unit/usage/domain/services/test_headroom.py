"""Unit tests for usage.domain.services.headroom.

Headroom and relevant-window cases over our UsageSnapshot type.
UsageWindow.pct/ScopedWindow.pct are always float by construction (parsed in
usage_snapshot.py), so malformed-pct inputs don't exist at this layer —
there is no untyped input to guard against.
"""

from claude_acc_manager.usage.domain.services.headroom import account_headroom, relevant_windows
from claude_acc_manager.usage.domain.usage_snapshot import ScopedWindow, UsageSnapshot, UsageWindow


def _snapshot(
    five_hour: float | None = None,
    seven_day: float | None = None,
    scoped: tuple[ScopedWindow, ...] = (),
) -> UsageSnapshot:
    return UsageSnapshot(
        five_hour=None if five_hour is None else UsageWindow(pct=five_hour, resets_at=None),
        seven_day=None if seven_day is None else UsageWindow(pct=seven_day, resets_at=None),
        scoped=scoped,
    )


class TestAccountHeadroom:
    """headroom = 100 - max(pct over the binding windows)."""

    def test_binding_window_is_the_higher_utilization(self):
        assert account_headroom(_snapshot(five_hour=80.0, seven_day=20.0)) == 20.0

    def test_seven_day_can_bind_over_five_hour(self):
        assert account_headroom(_snapshot(five_hour=20.0, seven_day=80.0)) == 20.0

    def test_single_present_window_binds_alone(self):
        assert account_headroom(_snapshot(five_hour=35.0)) == 65.0

    def test_at_limit_is_zero_headroom(self):
        assert account_headroom(_snapshot(five_hour=100.0, seven_day=0.0)) == 0.0

    def test_no_window_data_is_unknown(self):
        assert account_headroom(_snapshot()) is None

    def test_no_snapshot_is_unknown(self):
        assert account_headroom(None) is None

    def test_scoped_window_ignored_without_a_models_argument(self):
        # arrange — Fable at 100% would bind if folded in, but models=() excludes it
        snapshot = _snapshot(
            five_hour=10.0, seven_day=5.0, scoped=(ScopedWindow("Fable", 100.0, None),)
        )

        # act / assert
        assert account_headroom(snapshot) == 90.0


class TestModelScopedFolding:
    """A named model-scoped weekly window binds just as hard as 5h/7d."""

    def test_named_model_folds_into_the_binding_window(self):
        snapshot = _snapshot(
            five_hour=20.0, seven_day=10.0, scoped=(ScopedWindow("Fable", 95.0, None),)
        )
        assert account_headroom(snapshot, models=("Fable",)) == 5.0

    def test_maxed_model_binds_despite_session_headroom(self):
        snapshot = _snapshot(
            five_hour=10.0, seven_day=10.0, scoped=(ScopedWindow("Fable", 100.0, None),)
        )
        assert account_headroom(snapshot, models=("Fable",)) == 0.0

    def test_model_match_is_case_insensitive(self):
        snapshot = _snapshot(scoped=(ScopedWindow("Fable", 95.0, None),))
        assert account_headroom(snapshot, models=("fable",)) == 5.0

    def test_unlisted_model_does_not_bind(self):
        snapshot = _snapshot(
            five_hour=20.0, seven_day=10.0, scoped=(ScopedWindow("Fable", 99.0, None),)
        )
        assert account_headroom(snapshot, models=("Opus",)) == 80.0

    def test_multiple_models_take_the_worst(self):
        snapshot = _snapshot(
            scoped=(ScopedWindow("Fable", 60.0, None), ScopedWindow("Opus", 90.0, None))
        )
        assert account_headroom(snapshot, models=("Fable", "Opus")) == 10.0

    def test_all_sentinel_matches_every_scoped_window(self):
        snapshot = _snapshot(
            scoped=(ScopedWindow("Fable", 60.0, None), ScopedWindow("Opus", 90.0, None))
        )
        assert account_headroom(snapshot, models=("all",)) == 10.0

    def test_all_sentinel_is_case_insensitive(self):
        snapshot = _snapshot(scoped=(ScopedWindow("Fable", 60.0, None),))
        assert account_headroom(snapshot, models=("ALL",)) == 40.0


class TestRelevantWindows:
    """The single canonical window source shared by headroom and poll_policy."""

    def test_carries_labels_pcts_and_resets(self):
        snapshot = UsageSnapshot(
            five_hour=UsageWindow(pct=62.0, resets_at="2026-05-23T13:30:00Z"),
            seven_day=UsageWindow(pct=27.0, resets_at="2026-05-27T13:00:00Z"),
            scoped=(),
        )
        assert relevant_windows(snapshot) == (
            ("5h", 62.0, "2026-05-23T13:30:00Z"),
            ("7d", 27.0, "2026-05-27T13:00:00Z"),
        )

    def test_scoped_excluded_without_models(self):
        snapshot = _snapshot(scoped=(ScopedWindow("Fable", 84.0, None),))
        assert relevant_windows(snapshot) == ()

    def test_none_snapshot_yields_no_windows(self):
        assert relevant_windows(None) == ()
