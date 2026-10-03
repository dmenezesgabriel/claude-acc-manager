"""Unit tests for usage.domain.usage_snapshot."""

import json
from pathlib import Path

from claude_acc_manager.usage.domain.usage_snapshot import (
    ScopedWindow,
    UsageWindow,
    usage_snapshot_from_response,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class TestFiveHourAndSevenDay:
    """The two windows every response carries."""

    def test_parses_both_windows_from_the_minimal_response(self):
        # arrange
        data = load_fixture("usage_response_minimal.json")

        # act
        snapshot = usage_snapshot_from_response(data)

        # assert
        assert snapshot.five_hour == UsageWindow(pct=15.0, resets_at="2026-05-23T13:30:00Z")
        assert snapshot.seven_day == UsageWindow(pct=8.0, resets_at="2026-05-27T13:00:00Z")

    def test_missing_window_is_none_not_a_crash(self):
        assert usage_snapshot_from_response({}).five_hour is None
        assert usage_snapshot_from_response({}).seven_day is None

    def test_malformed_utilization_drops_just_that_window(self):
        # arrange — utilization missing/non-numeric must not raise
        data = {"five_hour": {"utilization": "not-a-number"}}

        # act / assert
        assert usage_snapshot_from_response(data).five_hour is None

    def test_bool_utilization_is_not_a_number(self):
        # arrange — bool is an int subclass in Python; must not pass as a pct
        data = {"five_hour": {"utilization": True}}

        # act / assert
        assert usage_snapshot_from_response(data).five_hour is None

    def test_missing_resets_at_is_none(self):
        # arrange
        data = {"five_hour": {"utilization": 10.0}}

        # act
        snapshot = usage_snapshot_from_response(data)

        # assert
        assert snapshot.five_hour == UsageWindow(pct=10.0, resets_at=None)

    def test_a_non_string_resets_at_is_dropped(self):
        # arrange — resets_at is optional metadata; a malformed one is None
        data = {"five_hour": {"utilization": 10.0, "resets_at": 1_700_000_000}}

        # act
        snapshot = usage_snapshot_from_response(data)

        # assert
        assert snapshot.five_hour == UsageWindow(pct=10.0, resets_at=None)


class TestUnknownFieldsAreIgnored:
    """The endpoint is undocumented and its shape drifts — unknown keys never crash."""

    def test_unmodeled_top_level_key_is_ignored(self):
        # arrange — "tangelo" and "seven_day_sonnet" are not modeled fields
        data = load_fixture("usage_response_full.json")

        # act
        snapshot = usage_snapshot_from_response(data)

        # assert — no crash, and the two real windows still parse
        assert snapshot.five_hour is not None
        assert snapshot.seven_day is not None

    def test_non_dict_response_shape_still_yields_empty_fields(self):
        assert usage_snapshot_from_response({"five_hour": "not-a-window"}).five_hour is None


class TestScopedWeeklyWindows:
    """Per-model weekly windows come only from limits[] entries naming a model."""

    def test_extracts_the_model_scoped_entry_by_display_name(self):
        # arrange
        data = load_fixture("usage_response_full.json")

        # act
        snapshot = usage_snapshot_from_response(data)

        # assert
        assert snapshot.scoped == (
            ScopedWindow(name="Fable", pct=84.0, resets_at="2026-05-27T13:00:00Z"),
        )

    def test_entries_without_a_model_display_name_are_excluded(self):
        # arrange — session/weekly_all/unknown-kind entries carry no scope.model
        data = load_fixture("usage_response_full.json")

        # act
        scoped_names = {w.name for w in usage_snapshot_from_response(data).scoped}

        # assert — only the one named model surfaces, kind is never checked
        assert scoped_names == {"Fable"}

    def test_missing_limits_array_is_no_scoped_windows(self):
        assert usage_snapshot_from_response({}).scoped == ()

    def test_non_list_limits_is_tolerated(self):
        assert usage_snapshot_from_response({"limits": "not-a-list"}).scoped == ()

    def test_non_dict_limits_entry_is_skipped(self):
        # arrange — a stray non-object entry must not crash the whole array
        data = {
            "limits": [
                None,
                {"scope": {"model": {"display_name": "Fable"}}, "percent": 84},
            ]
        }

        # act / assert
        assert usage_snapshot_from_response(data).scoped == (
            ScopedWindow(name="Fable", pct=84.0, resets_at=None),
        )

    def test_limits_entry_missing_percent_is_dropped(self):
        # arrange
        data = {"limits": [{"scope": {"model": {"display_name": "Fable"}}}]}

        # act / assert
        assert usage_snapshot_from_response(data).scoped == ()

    def test_empty_display_name_is_dropped(self):
        # arrange — a blank name is a string, so it must fail on its own,
        # independent of the isinstance check (pins the `or`, not `and`)
        data = {"limits": [{"scope": {"model": {"display_name": ""}}, "percent": 50}]}

        # act / assert
        assert usage_snapshot_from_response(data).scoped == ()
