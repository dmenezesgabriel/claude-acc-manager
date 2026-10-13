"""TUI renderers — bars: bar_cells, usage_bar, usage_rows.

Pure functions over domain objects producing Rich ``Text``; assertions pin
the plain-text shape and the style spans (severity color, threshold tick).
"""

from support.rich_asserts import span_styles as _span_styles
from support.rich_asserts import text_style_at as _style_at
from support.tui_views import DARK, NOW
from support.tui_views import iso as _iso
from support.tui_views import usage_snapshot as _snapshot

from claude_acc_manager.tui.formatting import bar_cells, usage_bar, usage_rows
from claude_acc_manager.tui.theme import CAM_LIGHT, Palette
from claude_acc_manager.usage.domain.usage_snapshot import (
    ScopedWindow,
    UsageSnapshot,
    UsageWindow,
)


class TestBarCells:
    def test_none_pct_is_all_track(self) -> None:
        text = bar_cells(None, 5, palette=DARK)
        assert text.plain == "─────"
        assert len(text.spans) == 1
        assert _style_at(text, 0) == DARK.track

    def test_a_full_bar_fills_in_severity_color(self) -> None:
        text = bar_cells(100.0, 5, palette=DARK)
        assert text.plain == "━━━━━"
        assert all(style == DARK.sev_crit for style in _span_styles(text))
        assert _style_at(text, 0) == DARK.sev_crit
        assert _style_at(text, 4) == DARK.sev_crit

    def test_the_severity_bands(self) -> None:
        # the fill cell wears the band color; the track cell stays neutral
        bands = ((50.0, DARK.sev_ok), (80.0, DARK.sev_warn), (95.0, DARK.sev_crit))
        for pct, expected in bands:
            text = bar_cells(pct, 10, palette=DARK)
            assert _style_at(text, 0) == expected

    def test_a_half_cell_renders_at_the_boundary(self) -> None:
        # 45% of width 10 = 4.5 cells → four full, one half, five track
        text = bar_cells(45.0, 10, palette=DARK)
        assert text.plain == "━━━━╸─────"
        # the half cell wears the fill color, not the track's
        assert _style_at(text, 4) == DARK.sev_ok
        assert _style_at(text, 5) == DARK.track

    def test_a_sub_half_fraction_stays_track(self) -> None:
        # 42% of width 10 = 4.2 cells → no half glyph
        assert bar_cells(42.0, 10, palette=DARK).plain == "━━━━──────"

    def test_a_tiny_pct_still_shows_a_half_cell(self) -> None:
        # 0.5% of width 100 = 0.5 cells → the half glyph marks nonzero usage
        assert bar_cells(0.5, 100, palette=DARK).plain == "╸" + "─" * 99

    def test_the_threshold_tick_overrides_the_fill(self) -> None:
        # 90% of width 10 → tick lands on cell 9, over the filled region
        text = bar_cells(95.0, 10, threshold=90.0, palette=DARK)
        assert text.plain[9] == "┃"
        assert DARK.sev_warn in _style_at(text, 9)
        assert DARK.sev_warn not in _style_at(text, 8)

    def test_the_tick_lands_mid_bar(self) -> None:
        text = bar_cells(20.0, 10, threshold=50.0, palette=DARK)
        assert text.plain[5] == "┃"
        assert DARK.sev_warn in _style_at(text, 5)

    def test_a_zero_threshold_ticks_the_first_cell(self) -> None:
        text = bar_cells(20.0, 10, threshold=0.0, palette=DARK)
        assert text.plain[0] == "┃"

    def test_stale_fill_is_dimmed(self) -> None:
        text = bar_cells(50.0, 4, stale=True, palette=DARK)
        assert _style_at(text, 0) == f"{DARK.sev_ok} dim"
        # track cells stay undimmed — only the measurement is stale
        assert _style_at(text, 3) == DARK.track

    def test_negative_and_over_100_clamp(self) -> None:
        assert bar_cells(-20.0, 4, palette=DARK).plain == "────"
        assert bar_cells(150.0, 4, palette=DARK).plain == "━━━━"

    def test_a_100_threshold_ticks_the_last_cell(self) -> None:
        # the tick is clamped inside the bar — a 100% trigger must still land
        text = bar_cells(20.0, 10, threshold=100.0, palette=DARK)
        assert text.plain[9] == "┃"

    def test_the_tick_rounds_against_the_pct_denominator(self) -> None:
        # 50% of width 11 → round(5.5) = 6; a denominator off by one lands at 5
        text = bar_cells(10.0, 11, threshold=50.0, palette=DARK)
        assert text.plain[6] == "┃"

    def test_a_whole_boundary_cell_keeps_the_track_style(self) -> None:
        # 50% of 10 → exactly five full cells; the cell at index 5 is a whole
        # empty cell — neither inside the fill nor a half — and stays track
        text = bar_cells(50.0, 10, palette=DARK)
        assert text.plain[5] == "─"
        assert _style_at(text, 5) == DARK.track


class TestUsageBar:
    def test_a_known_pct_line(self) -> None:
        text = usage_bar("5h", 47.0, "resets 2h 13m", 10, palette=DARK)
        assert text.plain == "5h ━━━━╸─────  47%  resets 2h 13m"
        assert _style_at(text, 0) == DARK.muted  # the label
        assert _style_at(text, 14) == DARK.sev_ok  # the pct
        assert _style_at(text, 19) == DARK.muted  # the suffix

    def test_an_unknown_pct_line(self) -> None:
        text = usage_bar("5h", None, None, 5, palette=DARK)
        assert text.plain == "5h ─────  usage unknown"
        assert _style_at(text, 8) == DARK.muted

    def test_no_suffix_leaves_no_trailing_gap(self) -> None:
        text = usage_bar("7d", 63.0, None, 4, palette=DARK)
        assert text.plain == "7d ━━╸─  63%"

    def test_fresh_lines_are_not_dimmed(self) -> None:
        text = usage_bar("5h", 47.0, None, 10, palette=DARK)
        assert " dim" not in "".join(_span_styles(text))

    def test_a_stale_line_dims_pct_and_bar(self) -> None:
        text = usage_bar("5h", 47.0, None, 10, stale=True, palette=DARK)
        assert _style_at(text, 3) == f"{DARK.sev_ok} dim"
        assert _style_at(text, 14) == f"{DARK.sev_ok} dim"

    def test_the_threshold_kwarg_reaches_the_bar(self) -> None:
        text = usage_bar("5h", 95.0, None, 10, threshold=90.0, palette=DARK)
        assert text.plain[12] == "┃"

    def test_the_palette_kwarg_reaches_everything(self) -> None:
        light = Palette.from_theme(CAM_LIGHT)
        text = usage_bar("5h", 47.0, "resets 1h", 5, palette=light)
        assert _style_at(text, 3) == light.sev_ok
        assert _style_at(text, 0) == light.muted


class TestUsageRows:
    def test_no_snapshot_means_no_rows(self) -> None:
        assert usage_rows(None, NOW) == []

    def test_the_two_windows_in_order(self) -> None:
        rows = usage_rows(_snapshot(), NOW)
        assert [row[0] for row in rows] == ["5h", "7d"]
        assert rows[0][1] == 47.0
        assert rows[0][2] == "resets 2h 13m"
        assert rows[0][3].startswith("resets 2h 13m · ")

    def test_a_missing_window_drops_its_row(self) -> None:
        rows = usage_rows(_snapshot(seven_day=None), NOW)
        assert [row[0] for row in rows] == ["5h"]

    def test_an_elapsed_reset_drops_the_clock(self) -> None:
        # once the reset has passed there is no absolute clock to append —
        # the wide suffix equals the countdown, never "resets now · None"
        snap = UsageSnapshot(
            five_hour=UsageWindow(pct=50.0, resets_at=_iso(NOW - 60)),
            seven_day=None,
            scoped=(),
        )
        rows = usage_rows(snap, NOW)
        assert rows[0][2] == "resets now"
        assert rows[0][3] == "resets now"

    def test_a_scoped_window_carries_its_name(self) -> None:
        rows = usage_rows(_snapshot(scoped=(ScopedWindow("Fable", 40.0, None),)), NOW)
        assert rows[-1][0] == "Fable"
        assert rows[-1][1] == 40.0
        # no reset, no marker — the suffix is empty
        assert rows[-1][2] == ""

    def test_a_maxed_scoped_window_is_flagged(self) -> None:
        rows = usage_rows(_snapshot(scoped=(ScopedWindow("Fable", 100.0, None),)), NOW)
        assert rows[-1][2].endswith("(!)")

    def test_a_7d_window_ahead_of_pace_is_marked(self) -> None:
        # resets in ~5.5d → elapsed 1.5d of 7d → expected ~21%, actual 60 → ahead
        window = UsageWindow(pct=60.0, resets_at=_iso(NOW + 5.5 * 86400))
        snap = UsageSnapshot(five_hour=None, seven_day=window, scoped=())
        rows = usage_rows(snap, NOW, NOW)
        assert rows[0][2] == "resets 5d 12h  (ahead of pace)"

    def test_a_scoped_row_carries_reset_and_pace(self) -> None:
        # scoped windows are weekly too — the row keeps both its reset and,
        # when ahead of schedule, the pace marker
        rows = usage_rows(
            _snapshot(scoped=(ScopedWindow("Fable", 60.0, _iso(NOW + 5.5 * 86400)),)),
            NOW,
            NOW,
        )
        assert rows[-1][2] == "resets 5d 12h  (ahead of pace)"
        # the wide variant keeps all three parts: reset, clock, pace marker
        assert rows[-1][3].startswith("resets 5d 12h · ")
        assert rows[-1][3].endswith("  (ahead of pace)")

    def test_a_5h_window_never_gets_a_pace_marker(self) -> None:
        # the label gates the marker, not the window's horizon: a contrived
        # 5h window whose reset sits 5.5d out would read "ahead of pace" —
        # the 5h row must still never show it
        snap = UsageSnapshot(
            five_hour=UsageWindow(pct=60.0, resets_at=_iso(NOW + 5.5 * 86400)),
            seven_day=None,
            scoped=(),
        )
        rows = usage_rows(snap, NOW, NOW)
        assert "ahead" not in rows[0][2]
        assert "ahead" not in rows[0][3]
