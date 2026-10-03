"""Pure renderers for the TUI — bars, card text, mini lines.

Everything here is a pure function over domain objects producing a Rich
``Text``; assertions pin the plain-text shape and the style spans that
carry meaning (severity color, dim-on-stale, the threshold tick).
"""

from datetime import UTC, datetime

from rich.text import Text
from support.fake_usage_api import FakeUsageApi
from support.rich_asserts import span_styles as _span_styles
from support.rich_asserts import text_style_at as _style_at
from support.tui_app import settle_workers, wired_app
from support.use_cases import make_account
from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import ListView, Static

from claude_acc_manager.accounts.application.use_cases.collect_accounts_view import (
    AccountView,
)
from claude_acc_manager.accounts.domain.entities import Account
from claude_acc_manager.tui.formatting import format_duration
from claude_acc_manager.tui.theme import CAM_DARK, CAM_LIGHT, MUTED_LIGHT, Palette
from claude_acc_manager.tui.widgets import (
    AccountCard,
    AccountItem,
    AccountsPanel,
    MenuItem,
    _join_blocks,
    account_card_text,
    bar_cells,
    mini_account_text,
    usage_bar,
    usage_rows,
)
from claude_acc_manager.usage.domain.services.poll_policy import TRUST_MAX_AGE_S
from claude_acc_manager.usage.domain.usage_cache_entry import UsageCacheEntry
from claude_acc_manager.usage.domain.usage_snapshot import (
    ScopedWindow,
    UsageSnapshot,
    UsageWindow,
)

DARK = Palette.from_theme(CAM_DARK)
LIGHT = Palette.from_theme(CAM_LIGHT)
NOW = 1_800_000_000.0


def _iso(epoch_s: float) -> str:
    """The ``resets_at`` wire shape for a known epoch."""
    return datetime.fromtimestamp(epoch_s, tz=UTC).isoformat()


def _view(
    name: str = "work",
    *,
    is_active: bool = False,
    is_quarantined: bool = False,
    enabled: bool = True,
    last_good: UsageSnapshot | None = None,
    fetched_at_s: float | None = NOW,
    last_error: str | None = None,
) -> AccountView:
    """An AccountView with the usage fields the renderers read."""
    account = make_account(name)
    if not enabled:
        account = Account(
            name=account.name,
            email=account.email,
            account_uuid=account.account_uuid,
            organization_uuid=account.organization_uuid,
            organization_name=account.organization_name,
            added_at=account.added_at,
            enabled=False,
        )
    return AccountView(
        account=account,
        is_active=is_active,
        is_quarantined=is_quarantined,
        has_credentials=True,
        usage=UsageCacheEntry(
            last_good=last_good,
            fetched_at_s=fetched_at_s,
            consecutive_failures=0,
            last_error=last_error,
            backoff_until_s=None,
            last_429_at_s=None,
            next_poll_at_s=None,
            poll_interval_s=None,
        ),
    )


def _snapshot(
    five_hour: float | None = 47.0,
    seven_day: float | None = 63.0,
    scoped: tuple[ScopedWindow, ...] = (),
) -> UsageSnapshot:
    """A snapshot with the standard two windows, scoped extras optional."""
    return UsageSnapshot(
        five_hour=None
        if five_hour is None
        else UsageWindow(pct=five_hour, resets_at=_iso(NOW + 7980)),
        seven_day=None
        if seven_day is None
        else UsageWindow(pct=seven_day, resets_at=_iso(NOW + 500_000)),
        scoped=scoped,
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


class TestAccountCardText:
    def test_the_header_names_and_marks_the_account(self) -> None:
        text = account_card_text(
            _view("work", is_active=True, last_good=_snapshot()),
            80,
            threshold=90.0,
            now=NOW,
            palette=DARK,
        )
        first = text.plain.splitlines()[0]
        assert first == "work (work@example.com)   ● active"
        assert _style_at(text, 0) == f"bold {DARK.accent}"
        dot_at = text.plain.index("●")
        assert _style_at(text, dot_at) == f"bold {DARK.accent}"

    def test_disabled_and_fresh_age_markers(self) -> None:
        text = account_card_text(
            _view("work", enabled=False, last_good=_snapshot(), fetched_at_s=NOW - 200),
            80,
            now=NOW,
            palette=DARK,
        )
        first = text.plain.splitlines()[0]
        assert first == "work (work@example.com)   (disabled)   · 3m ago"
        disabled_at = text.plain.index("(disabled)")
        assert _style_at(text, disabled_at) == DARK.muted
        age_at = text.plain.index("3m ago")
        assert _style_at(text, age_at) == DARK.muted

    def test_the_email_span_uses_the_foreground(self) -> None:
        text = account_card_text(_view("work", last_good=_snapshot()), 80, now=NOW, palette=DARK)
        email_at = text.plain.index("(")
        assert _style_at(text, email_at) == DARK.foreground

    def test_no_usage_reads_unavailable_with_the_error(self) -> None:
        text = account_card_text(
            _view("work", last_good=None, last_error="http-429"),
            80,
            now=NOW,
            palette=DARK,
        )
        assert text.plain.splitlines()[1] == "    usage unavailable · http-429"
        unavailable_at = text.plain.index("usage unavailable")
        assert _style_at(text, unavailable_at) == DARK.muted
        error_at = text.plain.index("http-429")
        assert _style_at(text, error_at) == DARK.muted

    def test_a_quarantined_account_shows_the_warning(self) -> None:
        text = account_card_text(
            _view("work", is_quarantined=True, last_good=None, last_error="x"),
            80,
            now=NOW,
            palette=DARK,
        )
        lines = text.plain.splitlines()
        assert lines[1] == "    ⚠ quarantined — dead refresh-token lineage"
        # the warning line sits at offset len(first)+1
        warn_at = text.plain.index("⚠")
        assert DARK.sev_warn in _style_at(text, warn_at)

    def test_bar_rows_render_under_the_header(self) -> None:
        text = account_card_text(
            _view("work", is_active=True, last_good=_snapshot()),
            80,
            threshold=90.0,
            now=NOW,
            palette=DARK,
        )
        lines = text.plain.splitlines()
        assert "5h" in lines[1] and "━" in lines[1]
        assert "7d" in lines[2]

    def test_the_threshold_tick_reaches_the_card(self) -> None:
        # a 95% bar crossed by the 90% tick — the auto-switch trigger line
        snap = UsageSnapshot(
            five_hour=UsageWindow(pct=95.0, resets_at=None),
            seven_day=None,
            scoped=(),
        )
        text = account_card_text(
            _view("work", is_active=True, last_good=snap),
            80,
            threshold=90.0,
            now=NOW,
            palette=DARK,
        )
        assert "┃" in text.plain

    def test_resets_use_the_render_clock_not_fetch_time(self) -> None:
        # fetched_at_s ≠ now: the countdown is against now, the pace math
        # against the measurement's own clock
        snap = UsageSnapshot(
            five_hour=UsageWindow(pct=50.0, resets_at=_iso(NOW + 7980)),
            seven_day=UsageWindow(pct=60.0, resets_at=_iso(NOW + 5.5 * 86400)),
            scoped=(),
        )
        text = account_card_text(
            _view("work", is_active=True, last_good=snap, fetched_at_s=NOW - 300),
            80,
            now=NOW,
            palette=DARK,
        )
        assert "resets 2h 13m" in text.plain
        assert "(ahead of pace)" in text.plain

    def test_stale_rows_dim(self) -> None:
        text = account_card_text(
            _view(
                "work",
                is_active=True,
                last_good=_snapshot(),
                fetched_at_s=NOW - TRUST_MAX_AGE_S - 60,
            ),
            80,
            now=NOW,
            palette=DARK,
        )
        assert any("dim" in style for style in _span_styles(text))

    def test_rows_at_exactly_the_trust_age_stay_fresh(self) -> None:
        text = account_card_text(
            _view(
                "work",
                last_good=_snapshot(),
                fetched_at_s=NOW - TRUST_MAX_AGE_S,
            ),
            80,
            now=NOW,
            palette=DARK,
        )
        assert "dim" not in "".join(_span_styles(text))

    def test_a_never_fetched_account_shows_no_age(self) -> None:
        text = account_card_text(
            _view("work", last_good=None, fetched_at_s=None),
            80,
            now=NOW,
            palette=DARK,
        )
        assert "ago" not in text.plain

    def test_the_clock_suffix_drops_when_the_row_is_narrow(self) -> None:
        # a long scoped name inflates the row overhead past the clock's fit
        long_name = "Fable-" + "x" * 34
        snap = _snapshot(scoped=(ScopedWindow(long_name, 40.0, None),))
        wide = account_card_text(
            _view("work", is_active=True, last_good=snap), 100, now=NOW, palette=DARK
        )
        narrow = account_card_text(
            _view("work", is_active=True, last_good=snap), 64, now=NOW, palette=DARK
        )
        wide_row = next(r for r in wide.plain.splitlines() if "5h" in r)
        narrow_row = next(r for r in narrow.plain.splitlines() if "5h" in r)
        assert "·" in wide_row
        assert "·" not in narrow_row
        # the bar floor holds at 12 cells even when the card runs out of room
        assert sum(narrow_row.count(g) for g in "━─╸┃") == 12
        # label column stays left-padded to the longest name
        assert narrow.plain.splitlines()[1].startswith("    5h " + " " * 38)

    def test_the_bar_width_tracks_the_card_width(self) -> None:
        # width 57 → bar_width min(30, 57-42-2) = 13 cells
        text = account_card_text(_view("work", last_good=_snapshot()), 57, now=NOW, palette=DARK)
        row = next(r for r in text.plain.splitlines() if "5h" in r)
        assert sum(row.count(g) for g in "━─╸┃") == 13

    def test_the_clock_suffix_fits_at_exactly_the_row_width(self) -> None:
        # bar floored at 12 → row_overhead 26; the 5h clock suffix (21 chars)
        # fits at width 47 and drops at 46 — the check is inclusive
        view = _view("work", last_good=_snapshot())
        fits = account_card_text(view, 47, now=NOW, palette=DARK)
        drops = account_card_text(view, 46, now=NOW, palette=DARK)
        fit_row = next(r for r in fits.plain.splitlines() if "5h" in r)
        drop_row = next(r for r in drops.plain.splitlines() if "5h" in r)
        assert "·" in fit_row
        assert "·" not in drop_row

    def test_the_palette_reaches_the_bar_cells(self) -> None:
        # a dropped palette kwarg inside the row loop falls back to dark
        text = account_card_text(_view("work", last_good=_snapshot()), 80, now=NOW, palette=LIGHT)
        row_end = text.plain.index("5h")
        assert _style_at(text, row_end + 3) == LIGHT.sev_ok


class TestMiniAccountText:
    def test_the_one_line_summary(self) -> None:
        text = mini_account_text(_view("work", last_good=_snapshot()), NOW, palette=DARK)
        assert "(work@example.com)   5h" in text.plain
        assert "47% · 7d" in text.plain
        # the " · " separator between parts rides the track color
        dot_at = text.plain.index("·")
        assert _style_at(text, dot_at) == DARK.track

    def test_the_header_pins_its_wrap_behavior_and_styles(self) -> None:
        text = mini_account_text(_view("work", last_good=_snapshot()), NOW, palette=DARK)
        # the mini line must not wrap — it ellipsizes instead
        assert text.no_wrap is True
        assert text.overflow == "ellipsis"
        assert _style_at(text, 0) == f"bold {DARK.accent}"
        email_at = text.plain.index("(")
        assert _style_at(text, email_at) == DARK.foreground

    def test_a_disabled_mini_marks_and_styles_it(self) -> None:
        text = mini_account_text(
            _view("work", enabled=False, last_good=_snapshot()), NOW, palette=DARK
        )
        assert text.plain.startswith("work (work@example.com)  (disabled)   ")
        disabled_at = text.plain.index("(disabled)")
        assert _style_at(text, disabled_at) == DARK.muted

    def test_a_5h_part_never_shows_a_pace_marker(self) -> None:
        # a contrived 5h window whose reset sits 5.5d out would read "ahead
        # of pace" — the label gate, not the horizon, withholds the marker
        snap = UsageSnapshot(
            five_hour=UsageWindow(pct=60.0, resets_at=_iso(NOW + 5.5 * 86400)),
            seven_day=None,
            scoped=(),
        )
        text = mini_account_text(_view("work", last_good=snap), NOW, palette=DARK)
        assert "(ahead)" not in text.plain

    def test_mini_segment_styles(self) -> None:
        text = mini_account_text(_view("work", last_good=_snapshot()), NOW, palette=DARK)
        label_at = text.plain.index("5h")
        assert _style_at(text, label_at) == DARK.muted

    def test_no_usage_reads_unknown(self) -> None:
        text = mini_account_text(_view("work", last_good=None), NOW, palette=DARK)
        assert text.plain.endswith("usage unknown")
        assert DARK.muted in _style_at(text, len(text.plain) - 1)

    def test_a_stale_measure_dims_its_pcts(self) -> None:
        text = mini_account_text(
            _view("work", last_good=_snapshot(), fetched_at_s=NOW - TRUST_MAX_AGE_S - 60),
            NOW,
            palette=DARK,
        )
        pct_at = text.plain.index("47%")
        assert _style_at(text, pct_at) == f"{DARK.sev_ok} dim"

    def test_a_fresh_measure_keeps_its_pcts_undimmed(self) -> None:
        # dim is the stale signal — a fresh pct wears the bare severity color
        text = mini_account_text(_view("work", last_good=_snapshot()), NOW, palette=DARK)
        pct_at = text.plain.index("47%")
        assert _style_at(text, pct_at) == DARK.sev_ok

    def test_a_disabled_account_is_marked(self) -> None:
        text = mini_account_text(
            _view("work", enabled=False, last_good=_snapshot()), NOW, palette=DARK
        )
        assert "(disabled)" in text.plain

    def test_a_maxed_window_carries_its_reset(self) -> None:
        snap = UsageSnapshot(
            five_hour=UsageWindow(pct=100.0, resets_at=_iso(NOW + 1800)),
            seven_day=None,
            scoped=(),
        )
        text = mini_account_text(_view("work", last_good=snap), NOW, palette=DARK)
        assert "100%" in text.plain
        assert "(resets 30m)" in text.plain
        reset_at = text.plain.index("(resets")
        assert _style_at(text, reset_at) == DARK.muted

    def test_a_maxed_scoped_window_joins_with_a_bang(self) -> None:
        snap = UsageSnapshot(
            five_hour=None,
            seven_day=None,
            scoped=(ScopedWindow("Fable", 100.0, None),),
        )
        text = mini_account_text(_view("work", last_good=snap), NOW, palette=DARK)
        assert "Fable (!)" in text.plain
        bang_at = text.plain.index("Fable")
        assert DARK.sev_crit in _style_at(text, bang_at)

    def test_a_7d_ahead_of_pace_is_flagged(self) -> None:
        snap = UsageSnapshot(
            five_hour=None,
            seven_day=UsageWindow(pct=60.0, resets_at=_iso(NOW + 5.5 * 86400)),
            scoped=(),
        )
        text = mini_account_text(_view("work", last_good=snap), NOW, palette=DARK)
        assert text.plain.endswith("(ahead)")
        ahead_at = text.plain.index("(ahead)")
        assert DARK.sev_warn in _style_at(text, ahead_at)

    def test_a_quarantined_account_shows_the_badge_instead(self) -> None:
        text = mini_account_text(
            _view("work", is_quarantined=True, last_good=_snapshot()),
            NOW,
            palette=DARK,
        )
        assert text.plain.endswith("⚠ quarantined")
        assert "47%" not in text.plain
        badge_at = text.plain.index("⚠")
        assert DARK.sev_warn in _style_at(text, badge_at)


class TestFormatDurationReuse:
    def test_the_bar_suffix_uses_the_same_clock_text(self) -> None:
        assert format_duration(7980) == "2h 13m"


class TestJoinBlocks:
    def test_minis_pack_tight_but_a_multiline_block_gets_air(self) -> None:
        blocks = [Text("card\nrow"), Text("mini1"), Text("mini2")]
        assert _join_blocks(blocks).plain == "card\nrow\n\nmini1\nmini2"

    def test_single_line_blocks_join_with_one_newline(self) -> None:
        blocks = [Text("a"), Text("b")]
        assert _join_blocks(blocks).plain == "a\nb"


class TestAccountsPanel:
    """The dashboard's monitor — Pilot-mounted inside a real CamApp."""

    async def test_loading_until_the_first_snapshot_lands(self, tmp_path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            panel = app.screen.query_one(AccountsPanel)
            app.snapshot = None
            text = panel.render()
            assert text.plain == "loading…"
            assert str(text.style) == DARK.muted

    async def test_the_active_card_then_the_minis(self, tmp_path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path, active_name="work")
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            text = app.screen.query_one(AccountsPanel).render().plain
            lines = text.splitlines()
            assert "● active" in lines[0]
            # the expanded card rows sit between the two account headers
            assert any(line.strip().startswith("5h") for line in lines)
            assert any("personal" in line and "·" not in line for line in lines)
            # a blank line separates the card from the minis, none between
            personal_at = next(i for i, r in enumerate(lines) if "personal" in r)
            assert lines[personal_at - 1] == ""

    async def test_no_accounts_reads_empty(self, tmp_path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path, names=())
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            panel = app.screen.query_one(AccountsPanel)
            text = panel.render()
            assert text.plain.startswith("No managed accounts yet")
            assert "cam add" in text.plain
            assert str(text.style) == DARK.muted

    async def test_minis_off_with_no_active_login_says_so(self, tmp_path) -> None:
        # the auto preview mounts the panel with minis off; nothing active
        # must not silently render a blank block
        app, _api, _store, _clock = wired_app(tmp_path)

        class _PanelScreen(Screen[None]):
            def compose(self) -> ComposeResult:
                yield AccountsPanel(show_minis=False)

        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app.push_screen(_PanelScreen())
            await pilot.pause()
            panel = app.screen.query_one(AccountsPanel)
            text = panel.render()
            assert text.plain == "no active managed login"
            assert str(text.style) == DARK.muted

    async def test_minis_off_with_an_active_login_shows_the_card(self, tmp_path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path, active_name="work")

        class _PanelScreen(Screen[None]):
            def compose(self) -> ComposeResult:
                yield AccountsPanel(show_minis=False)

        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app.push_screen(_PanelScreen())
            await pilot.pause()
            text = app.screen.query_one(AccountsPanel).render().plain
            assert "work" in text
            assert "personal" not in text

    async def test_a_theme_flip_repaints_the_panel(self, tmp_path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path, active_name="work")
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            panel = app.screen.query_one(AccountsPanel)
            assert MUTED_LIGHT not in _span_styles(panel.render())
            await pilot.press("ctrl+t")
            assert MUTED_LIGHT in _span_styles(panel.render())

    async def test_the_panel_forwards_the_app_threshold(self, tmp_path) -> None:
        # the seeded account reads 95% — the 90% trigger line must cross it
        hi = UsageSnapshot(
            five_hour=UsageWindow(pct=95.0, resets_at=None),
            seven_day=None,
            scoped=(),
        )
        app, _api, _store, _clock = wired_app(
            tmp_path, active_name="work", usage_api=FakeUsageApi(snapshot=hi)
        )
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            assert "┃" in app.screen.query_one(AccountsPanel).render().plain

    async def test_the_panel_repaints_on_snapshot_and_theme(self, tmp_path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path, active_name="work")
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            panel = app.screen.query_one(AccountsPanel)
            repaints: list[dict[str, object]] = []
            panel.refresh = lambda **kw: repaints.append(kw)
            app.snapshot = None
            app.theme = "cam-light"
            await pilot.pause()
            # the watcher's signature call is layout=True; a theme flip also
            # triggers Textual's own layout=False repaints — those don't count
            watcher_repaints = [kw for kw in repaints if kw == {"layout": True}]
            assert len(watcher_repaints) == 2

    async def test_unmounted_render_uses_the_fallback_width(self, tmp_path) -> None:
        # before first layout a widget's size is 0 — the fallback keeps the
        # card at its 30-cell bar width instead of collapsing to the floor
        app, _api, _store, _clock = wired_app(tmp_path, active_name="work")
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            text = AccountsPanel().render().plain
            line = next(line for line in text.splitlines() if "5h" in line)
            glyphs = sum(line.count(g) for g in "━─╸┃")
            assert glyphs == 30

    def test_the_panel_forwards_its_id(self) -> None:
        assert AccountsPanel(id="accounts-panel").id == "accounts-panel"

    def test_blocks_forward_the_palette_to_the_card(self) -> None:
        # unmounted: width falls back to _UNMOUNTED_WIDTH — a dropped palette
        # kwarg would render in the dark theme instead of the given one
        view = _view("work", is_active=True, last_good=_snapshot())
        blocks = AccountsPanel()._blocks((view,), NOW, 90.0, LIGHT)
        assert LIGHT.sev_ok in _span_styles(blocks[0])

    def test_blocks_forward_the_palette_to_the_minis(self) -> None:
        view = _view("work", is_active=False, last_good=_snapshot())
        blocks = AccountsPanel()._blocks((view,), NOW, 90.0, LIGHT)
        assert LIGHT.muted in _span_styles(blocks[0])


class _WidgetApp(App[None]):
    """Bare host — mounts fixtures without CamApp's poll machinery."""

    def __init__(self, *widgets: Widget, theme: str = "cam-dark") -> None:
        super().__init__()
        self._widgets = widgets
        self.register_theme(CAM_DARK)
        self.register_theme(CAM_LIGHT)
        self.theme = theme

    def compose(self) -> ComposeResult:
        yield from self._widgets

    def now_s(self) -> float:
        """The injected-clock seam the widgets read from the app."""
        return NOW


class TestAccountWidgets:
    async def test_an_account_item_renders_its_card(self) -> None:
        view = _view("work", is_active=True, last_good=None)
        app = _WidgetApp(ListView(AccountItem(view)))
        async with app.run_test() as pilot:
            await pilot.pause()
            item = app.screen.query_one(AccountItem)
            assert item.account_name.value == "work"
            text = app.screen.query_one(AccountCard).render().plain
            assert "work" in text
            assert "usage unavailable" in text

    async def test_the_card_passes_its_threshold_to_the_bar(self) -> None:
        snap = UsageSnapshot(
            five_hour=UsageWindow(pct=95.0, resets_at=None),
            seven_day=None,
            scoped=(),
        )
        app = _WidgetApp(AccountCard(_view("work", last_good=snap), threshold=90.0))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert "┃" in app.screen.query_one(AccountCard).render().plain

    async def test_an_unmounted_card_falls_back_to_full_width(self) -> None:
        # a falsy width must take the fallback branch, not a truthiness chain
        app = _WidgetApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            card = AccountCard(_view("work", last_good=_snapshot()))
            line = next(line for line in card.render().plain.splitlines() if "5h" in line)
            assert sum(line.count(g) for g in "━─╸┃") == 30

    async def test_the_card_render_uses_the_theme_palette(self) -> None:
        app = _WidgetApp(theme="cam-light")
        async with app.run_test() as pilot:
            await pilot.pause()
            card = AccountCard(_view("work", last_good=_snapshot()))
            assert LIGHT.sev_ok in _span_styles(card.render())

    async def test_set_account_repoints_and_repaints_the_card(self) -> None:
        app = _WidgetApp(ListView(AccountItem(_view("work", last_good=None))))
        async with app.run_test() as pilot:
            await pilot.pause()
            item = app.screen.query_one(AccountItem)
            card = app.screen.query_one(AccountCard)
            repaints: list[dict[str, object]] = []
            card.refresh = lambda **kw: repaints.append(kw)
            item.set_account(_view("personal", last_good=None))
            assert item.account_name.value == "personal"
            assert repaints == [{"layout": True}]
            assert "personal" in card.render().plain

    async def test_a_menu_item_carries_its_action(self) -> None:
        app = _WidgetApp(
            ListView(
                MenuItem("Switch [b]account[/b]", "switch"),
                MenuItem("Muted row", "none", muted=True),
            )
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            items = list(app.screen.query(MenuItem))
            assert items[0].action_id == "switch"
            label = items[0].query_one(Static)
            assert "menu-item-muted" not in label.classes
            # markup stays literal — labels are data, not formatting
            assert label.render().plain == "Switch [b]account[/b]"
            assert items[1].action_id == "none"
            assert "menu-item-muted" in items[1].query_one(Static).classes
