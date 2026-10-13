"""TUI renderers — account card and mini-account text.

Pure functions over domain objects producing Rich ``Text``; assertions pin
the plain-text shape and the style spans (dim-on-stale, severity color).
"""

from support.rich_asserts import text_style_at as _style_at
from support.rich_asserts import visual_plain as _visual_plain
from support.rich_asserts import visual_span_styles as _visual_span_styles
from support.rich_asserts import visual_style_at as _visual_style_at
from support.tui_views import DARK, LIGHT, NOW
from support.tui_views import account_view as _view
from support.tui_views import card_plain as _card_plain
from support.tui_views import iso as _iso
from support.tui_views import usage_snapshot as _snapshot

from claude_acc_manager.tui.formatting import format_duration, mini_account_text
from claude_acc_manager.tui.visuals import AccountCardVisual
from claude_acc_manager.usage.domain.services.poll_policy import TRUST_MAX_AGE_S
from claude_acc_manager.usage.domain.usage_snapshot import (
    ScopedWindow,
    UsageSnapshot,
    UsageWindow,
)


class TestAccountCardText:
    def test_the_header_names_and_marks_the_account(self) -> None:
        visual, plain = _card_plain(
            _view("work", is_active=True, last_good=_snapshot()),
            threshold=90.0,
        )
        first = plain.splitlines()[0]
        assert first == "work (work@example.com)   ● active"
        assert _visual_style_at(visual, 0, 400) == f"bold {DARK.accent}"
        assert _visual_style_at(visual, plain.index("●"), 400) == f"bold {DARK.accent}"

    def test_disabled_and_fresh_age_markers(self) -> None:
        visual, plain = _card_plain(
            _view("work", enabled=False, last_good=_snapshot(), fetched_at_s=NOW - 200),
        )
        first = plain.splitlines()[0]
        assert first == "work (work@example.com)   (disabled)   · 3m ago"
        assert _visual_style_at(visual, plain.index("(disabled)"), 400) == DARK.muted
        assert _visual_style_at(visual, plain.index("3m ago"), 400) == DARK.muted

    def test_the_email_span_uses_the_foreground(self) -> None:
        visual, plain = _card_plain(_view("work", last_good=_snapshot()))
        assert _visual_style_at(visual, plain.index("("), 400) == DARK.foreground

    def test_no_usage_reads_unavailable_with_the_error(self) -> None:
        visual, plain = _card_plain(
            _view("work", last_good=None, last_error="http-429"),
        )
        assert plain.splitlines()[1] == "    usage unavailable · http-429"
        assert _visual_style_at(visual, plain.index("usage unavailable"), 400) == DARK.muted
        assert _visual_style_at(visual, plain.index("http-429"), 400) == DARK.muted

    def test_a_quarantined_account_shows_the_warning(self) -> None:
        visual, plain = _card_plain(
            _view("work", is_quarantined=True, last_good=None, last_error="x"),
        )
        lines = plain.splitlines()
        assert lines[1] == "    ⚠ quarantined — dead refresh-token lineage"
        assert DARK.sev_warn in _visual_style_at(visual, plain.index("⚠"), 400)

    def test_bar_rows_render_under_the_header(self) -> None:
        _visual, plain = _card_plain(
            _view("work", is_active=True, last_good=_snapshot()),
            threshold=90.0,
        )
        lines = plain.splitlines()
        assert "5h" in lines[1] and "━" in lines[1]
        assert "7d" in lines[2]

    def test_the_threshold_tick_reaches_the_card(self) -> None:
        # a 95% bar crossed by the 90% tick — the auto-switch trigger line
        snap = UsageSnapshot(
            five_hour=UsageWindow(pct=95.0, resets_at=None),
            seven_day=None,
            scoped=(),
        )
        _visual, plain = _card_plain(
            _view("work", is_active=True, last_good=snap),
            threshold=90.0,
        )
        assert "┃" in plain

    def test_resets_use_the_render_clock_not_fetch_time(self) -> None:
        # fetched_at_s ≠ now: the countdown is against now, the pace math
        # against the measurement's own clock
        snap = UsageSnapshot(
            five_hour=UsageWindow(pct=50.0, resets_at=_iso(NOW + 7980)),
            seven_day=UsageWindow(pct=60.0, resets_at=_iso(NOW + 5.5 * 86400)),
            scoped=(),
        )
        _visual, plain = _card_plain(
            _view("work", is_active=True, last_good=snap, fetched_at_s=NOW - 300),
        )
        assert "resets 2h 13m" in plain
        assert "(ahead of pace)" in plain

    def test_stale_rows_dim(self) -> None:
        visual, _plain = _card_plain(
            _view(
                "work",
                is_active=True,
                last_good=_snapshot(),
                fetched_at_s=NOW - TRUST_MAX_AGE_S - 60,
            ),
        )
        assert any("dim" in style for style in _visual_span_styles(visual, 400))

    def test_rows_at_exactly_the_trust_age_stay_fresh(self) -> None:
        visual, _plain = _card_plain(
            _view(
                "work",
                last_good=_snapshot(),
                fetched_at_s=NOW - TRUST_MAX_AGE_S,
            ),
        )
        assert "dim" not in "".join(_visual_span_styles(visual, 400))

    def test_a_never_fetched_account_shows_no_age(self) -> None:
        _visual, plain = _card_plain(
            _view("work", last_good=None, fetched_at_s=None),
        )
        assert "ago" not in plain

    def test_the_clock_suffix_drops_when_the_row_is_narrow(self) -> None:
        # a long scoped name inflates the row overhead past the clock's fit
        long_name = "Fable-" + "x" * 34
        snap = _snapshot(scoped=(ScopedWindow(long_name, 40.0, None),))
        _wide, wide_plain = _card_plain(_view("work", is_active=True, last_good=snap), width=100)
        _narrow, narrow_plain = _card_plain(_view("work", is_active=True, last_good=snap), width=64)
        wide_row = next(r for r in wide_plain.splitlines() if "5h" in r)
        narrow_row = next(r for r in narrow_plain.splitlines() if "5h" in r)
        assert "·" in wide_row
        assert "·" not in narrow_row
        # the bar floor holds at 12 cells even when the card runs out of room
        assert sum(narrow_row.count(g) for g in "━─╸┃") == 12
        # label column stays left-padded to the longest name
        assert narrow_plain.splitlines()[1].startswith("    5h " + " " * 38)

    def test_the_bar_width_tracks_the_card_width(self) -> None:
        # width 57 → bar_width min(30, 57-42-2) = 13 cells
        _visual, plain = _card_plain(_view("work", last_good=_snapshot()), width=57)
        row = next(r for r in plain.splitlines() if "5h" in r)
        assert sum(row.count(g) for g in "━─╸┃") == 13

    def test_the_clock_suffix_fits_at_exactly_the_row_width(self) -> None:
        # bar floored at 12 → row_overhead 26; the 5h clock suffix (21 chars)
        # fits at width 47 and drops at 46 — the check is inclusive
        view = _view("work", last_good=_snapshot())
        _f, fits = _card_plain(view, width=47)
        _d, drops = _card_plain(view, width=46)
        fit_row = next(r for r in fits.splitlines() if "5h" in r)
        drop_row = next(r for r in drops.splitlines() if "5h" in r)
        assert "·" in fit_row
        assert "·" not in drop_row

    def test_the_palette_reaches_the_bar_cells(self) -> None:
        # a dropped palette kwarg inside the row loop falls back to dark
        visual = AccountCardVisual(
            _view("work", last_good=_snapshot()), 80, now=NOW, palette=LIGHT, redact=False
        )
        plain = _visual_plain(visual, 400)
        assert _visual_style_at(visual, plain.index("5h") + 3, 400) == LIGHT.sev_ok


class TestMiniAccountText:
    def test_the_one_line_summary(self) -> None:
        text = mini_account_text(
            _view("work", last_good=_snapshot()), NOW, palette=DARK, redact=False
        )
        assert "(work@example.com)   5h" in text.plain
        assert "47% · 7d" in text.plain
        # the " · " separator between parts rides the track color
        dot_at = text.plain.index("·")
        assert _style_at(text, dot_at) == DARK.track

    def test_redaction_drops_the_email_from_the_header(self) -> None:
        text = mini_account_text(
            _view("work", last_good=_snapshot()), NOW, palette=DARK, redact=True
        )
        assert "work@example.com" not in text.plain
        assert text.plain.startswith("work   ")

    def test_the_header_pins_its_wrap_behavior_and_styles(self) -> None:
        text = mini_account_text(
            _view("work", last_good=_snapshot()), NOW, palette=DARK, redact=False
        )
        # the mini line must not wrap — it ellipsizes instead
        assert text.no_wrap is True
        assert text.overflow == "ellipsis"
        assert _style_at(text, 0) == f"bold {DARK.accent}"
        email_at = text.plain.index("(")
        assert _style_at(text, email_at) == DARK.foreground

    def test_a_disabled_mini_marks_and_styles_it(self) -> None:
        text = mini_account_text(
            _view("work", enabled=False, last_good=_snapshot()), NOW, palette=DARK, redact=False
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
        text = mini_account_text(_view("work", last_good=snap), NOW, palette=DARK, redact=False)
        assert "(ahead)" not in text.plain

    def test_mini_segment_styles(self) -> None:
        text = mini_account_text(
            _view("work", last_good=_snapshot()), NOW, palette=DARK, redact=False
        )
        label_at = text.plain.index("5h")
        assert _style_at(text, label_at) == DARK.muted

    def test_no_usage_reads_unknown(self) -> None:
        text = mini_account_text(_view("work", last_good=None), NOW, palette=DARK, redact=False)
        assert text.plain.endswith("usage unknown")
        assert DARK.muted in _style_at(text, len(text.plain) - 1)

    def test_a_stale_measure_dims_its_pcts(self) -> None:
        text = mini_account_text(
            _view("work", last_good=_snapshot(), fetched_at_s=NOW - TRUST_MAX_AGE_S - 60),
            NOW,
            palette=DARK,
            redact=False,
        )
        pct_at = text.plain.index("47%")
        assert _style_at(text, pct_at) == f"{DARK.sev_ok} dim"

    def test_a_fresh_measure_keeps_its_pcts_undimmed(self) -> None:
        # dim is the stale signal — a fresh pct wears the bare severity color
        text = mini_account_text(
            _view("work", last_good=_snapshot()), NOW, palette=DARK, redact=False
        )
        pct_at = text.plain.index("47%")
        assert _style_at(text, pct_at) == DARK.sev_ok

    def test_a_disabled_account_is_marked(self) -> None:
        text = mini_account_text(
            _view("work", enabled=False, last_good=_snapshot()), NOW, palette=DARK, redact=False
        )
        assert "(disabled)" in text.plain

    def test_a_maxed_window_carries_its_reset(self) -> None:
        snap = UsageSnapshot(
            five_hour=UsageWindow(pct=100.0, resets_at=_iso(NOW + 1800)),
            seven_day=None,
            scoped=(),
        )
        text = mini_account_text(_view("work", last_good=snap), NOW, palette=DARK, redact=False)
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
        text = mini_account_text(_view("work", last_good=snap), NOW, palette=DARK, redact=False)
        assert "Fable (!)" in text.plain
        bang_at = text.plain.index("Fable")
        assert DARK.sev_crit in _style_at(text, bang_at)

    def test_a_7d_ahead_of_pace_is_flagged(self) -> None:
        snap = UsageSnapshot(
            five_hour=None,
            seven_day=UsageWindow(pct=60.0, resets_at=_iso(NOW + 5.5 * 86400)),
            scoped=(),
        )
        text = mini_account_text(_view("work", last_good=snap), NOW, palette=DARK, redact=False)
        assert text.plain.endswith("(ahead)")
        ahead_at = text.plain.index("(ahead)")
        assert DARK.sev_warn in _style_at(text, ahead_at)

    def test_a_quarantined_account_shows_the_badge_instead(self) -> None:
        text = mini_account_text(
            _view("work", is_quarantined=True, last_good=_snapshot()),
            NOW,
            palette=DARK,
            redact=False,
        )
        assert text.plain.endswith("⚠ quarantined")
        assert "47%" not in text.plain
        badge_at = text.plain.index("⚠")
        assert DARK.sev_warn in _style_at(text, badge_at)


class TestFormatDurationReuse:
    def test_the_bar_suffix_uses_the_same_clock_text(self) -> None:
        assert format_duration(7980) == "2h 13m"
