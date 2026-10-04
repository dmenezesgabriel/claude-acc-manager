"""The auto-switch preview — a dry-run view of the auto engine's pick.

The screen renders the active account's card, the candidates ``best``
would rank, and a decision log fed by the real
``switch.execute(strategy="best", dry_run=True)`` path — re-evaluated on
each snapshot, deduped so only outcome changes print. The fixed DRY-RUN
badge is the contract: nothing on this screen moves the live login.
"""

import threading
from dataclasses import replace
from pathlib import Path

from rich.text import Text
from support.fake_usage_api import FakeUsageApi
from support.in_memory_usage_cache import InMemoryUsageCache
from support.rich_asserts import strip_style_at, text_style_at
from support.tui_app import settle_workers, wired_app
from support.use_cases import make_account
from textual.widgets import RichLog, Static

from claude_acc_manager.accounts.application.ports import SwitchResult
from claude_acc_manager.accounts.domain.entities import QuarantineEntry
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.tui.app import CamApp
from claude_acc_manager.tui.autoview import AutoScreen
from claude_acc_manager.tui.dashboard import DashboardScreen
from claude_acc_manager.tui.formatting import clock_stamp
from claude_acc_manager.tui.theme import CAM_DARK, MUTED_LIGHT, Palette
from claude_acc_manager.tui.widgets import AccountsPanel
from claude_acc_manager.usage.application.ports import HttpTransportError
from claude_acc_manager.usage.domain.usage_cache_entry import (
    EMPTY_USAGE_CACHE_ENTRY,
    UsageCacheEntry,
)
from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot, UsageWindow

_BANNER = "— dry-run preview"
DARK = Palette.from_theme(CAM_DARK)


def _usage(pct: float | None) -> UsageCacheEntry:
    """A fresh cached measurement; ``pct=None`` means "never measured"."""
    last_good = (
        None
        if pct is None
        else UsageSnapshot(
            five_hour=UsageWindow(pct=pct, resets_at=None), seven_day=None, scoped=()
        )
    )
    return replace(EMPTY_USAGE_CACHE_ENTRY, last_good=last_good, fetched_at_s=1_000_000.0)


def _cache(**pcts: float | None) -> InMemoryUsageCache:
    """Seed per-account fresh measurements keyed by account name."""
    cache = InMemoryUsageCache()
    for name, pct in pcts.items():
        cache.save(name, _usage(pct))
    return cache


def _candidate_text(app: CamApp) -> Text:
    """The ranked-candidates renderable — style asserts read its spans."""
    content = app.screen.query_one("#candidates", Static).content
    assert isinstance(content, Text)
    return content


def _candidates(app: CamApp) -> str:
    """The rendered "Next best" block as plain text."""
    return _candidate_text(app).plain


def _log_lines(app: CamApp) -> list[str]:
    """Every strip of the decision log as plain text."""
    log = app.screen.query_one("#event-log", RichLog)
    return [strip.text.rstrip() for strip in log.lines]


async def _open_auto(pilot) -> None:
    """From the dashboard, ``g`` stacks the auto preview."""
    await pilot.press("g")
    await pilot.pause()


class _ParkingSwitch:
    """``execute`` parks the decision thread until the test opens the gate."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def execute(self, *_args: object, **_kwargs: object) -> SwitchResult:
        self.calls += 1
        self.entered.set()
        self.release.wait(timeout=10)
        return SwitchResult(outcome="already-best", dry_run=True)


class TestScreen:
    async def test_opens_with_the_dry_run_chrome(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path, active_name="work")
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_auto(pilot)
            assert isinstance(app.screen, AutoScreen)
            badge = app.screen.query_one("#mode-badge", Static)
            assert str(badge.content) == " DRY-RUN "
            assert badge.has_class("dry")
            summary = str(app.screen.query_one("#auto-summary", Static).content)
            assert summary == (f"auto-switch · threshold 90% · poll every {app.POLL_INTERVAL_S:g}s")
            panel = app.screen.query_one("#auto-active-panel", AccountsPanel)
            assert panel._show_minis is False
            app.screen.query_one("#auto-top")
            app.screen.query_one("#auto-title-row")
            app.screen.query_one("#candidates")
            log = app.screen.query_one("#event-log", RichLog)
            assert log.wrap is True

    def test_fresh_screen_state(self) -> None:
        screen = AutoScreen()
        assert screen._deciding is False
        assert screen._last_decision == ""

    async def test_escape_pops_back_to_the_dashboard(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_auto(pilot)
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, DashboardScreen)

    async def test_q_also_pops(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_auto(pilot)
            await pilot.press("q")
            await pilot.pause()
            assert isinstance(app.screen, DashboardScreen)

    async def test_opening_it_never_switches_the_live_account(self, tmp_path: Path) -> None:
        # work is pinned at its limit, personal is idle — the dry run still
        # decides "switched to 'personal'" while the live slot stays put.
        cache = _cache(work=95.0, personal=10.0)
        app, _api, store, _clock = wired_app(tmp_path, active_name="work", usage_cache=cache)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_auto(pilot)
            await settle_workers(pilot)
            active = store.active()
            assert active is not None and active.name.value == "work"
            assert any("dry run: switched to 'personal'" in line for line in _log_lines(app))


class TestCandidates:
    async def test_ranked_by_least_used_first(self, tmp_path: Path) -> None:
        cache = _cache(work=95.0, personal=60.0, alt=20.0)
        app, _api, _store, _clock = wired_app(
            tmp_path,
            names=("work", "personal", "alt"),
            active_name="work",
            usage_cache=cache,
        )
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_auto(pilot)
            await settle_workers(pilot)
            assert _candidates(app) == (
                "Next best\n"
                "  alt (alt@example.com)   20% used\n"
                "  personal (personal@example.com)   60% used"
            )
            text = _candidate_text(app)
            assert str(text.style) == DARK.muted
            assert text_style_at(text, text.plain.index("20% used")) == DARK.severity(20.0)
            assert text_style_at(text, text.plain.index("60% used")) == DARK.severity(60.0)

    async def test_the_active_account_is_not_a_candidate(self, tmp_path: Path) -> None:
        cache = _cache(work=95.0, personal=20.0)
        app, _api, _store, _clock = wired_app(tmp_path, active_name="work", usage_cache=cache)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_auto(pilot)
            assert "work" not in _candidates(app)

    async def test_ineligible_accounts_sort_last_with_markers(self, tmp_path: Path) -> None:
        app, _api, store, _clock = wired_app(
            tmp_path,
            names=("work", "personal", "alt"),
            active_name="work",
            usage_cache=_cache(work=95.0, personal=20.0, alt=30.0),
            usage_api=FakeUsageApi(error=HttpTransportError("down")),
        )
        store.set_enabled(AccountName("personal"), False)
        store.set_quarantined(
            QuarantineEntry("alt", "permanent_auth_error", "2026-09-10T12:00:00Z", None)
        )
        # "lost" was never given a parked login dir — no credential to move.
        store.upsert(make_account("lost"))
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_auto(pilot)
            await settle_workers(pilot)
            text = _candidates(app)
            assert "personal (personal@example.com)  (disabled)" in text
            assert "alt (alt@example.com)  ⚠ quarantined" in text
            assert "lost (lost@example.com)  no stored login" in text
            styled = _candidate_text(app)
            assert text_style_at(styled, styled.plain.index("(disabled)")) == DARK.muted
            assert text_style_at(styled, styled.plain.index("quarantined")) == DARK.muted
            assert text_style_at(styled, styled.plain.index("no stored login")) == DARK.muted

    async def test_unmeasured_accounts_sort_after_measured(self, tmp_path: Path) -> None:
        # alt is fresh-cached; personal's fetch fails so it stays unknown.
        cache = _cache(work=95.0, alt=20.0)
        app, _api, _store, _clock = wired_app(
            tmp_path,
            names=("work", "personal", "alt"),
            active_name="work",
            usage_cache=cache,
            usage_api=FakeUsageApi(error=HttpTransportError("down")),
        )
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_auto(pilot)
            await settle_workers(pilot)
            text = _candidates(app)
            assert "alt (alt@example.com)   20% used" in text
            assert "personal (personal@example.com)  usage unknown" in text
            assert text.index("20% used") < text.index("usage unknown")
            styled = _candidate_text(app)
            assert text_style_at(styled, styled.plain.index("usage unknown")) == DARK.muted

    async def test_a_single_account_has_no_candidates(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path, names=("work",), active_name="work")
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_auto(pilot)
            assert _candidates(app) == "Next best\n  no other accounts"
            styled = _candidate_text(app)
            assert text_style_at(styled, styled.plain.index("no other accounts")) == DARK.muted


class TestDecisionLog:
    async def test_the_banner_and_first_verdict_log_on_open(self, tmp_path: Path) -> None:
        cache = _cache(work=95.0, personal=10.0)
        app, _api, _store, _clock = wired_app(tmp_path, active_name="work", usage_cache=cache)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_auto(pilot)
            await settle_workers(pilot)
            lines = _log_lines(app)
            assert lines[0].startswith(_BANNER)
            assert lines[1].endswith("dry run: switched to 'personal' (was 'work')")
            log = app.screen.query_one("#event-log", RichLog)
            banner_seg = next(iter(log.lines[0]))
            assert str(banner_seg.style) == DARK.muted
            stamp = clock_stamp(app.now_s())
            verdict = log.lines[1]
            assert verdict.text.startswith(stamp)
            assert strip_style_at(verdict, 0) == DARK.muted
            assert strip_style_at(verdict, len(stamp) + 3) == DARK.accent

    async def test_an_unchanged_verdict_is_not_relogged(self, tmp_path: Path) -> None:
        cache = _cache(work=95.0, personal=10.0)
        app, _api, _store, clock = wired_app(tmp_path, active_name="work", usage_cache=cache)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_auto(pilot)
            await settle_workers(pilot)
            # a tick later the same verdict must not print again
            clock.advance(1)
            app.request_refresh()
            await settle_workers(pilot)
            lines = _log_lines(app)
            verdicts = [line for line in lines if "dry run:" in line]
            assert len(verdicts) == 1
            assert "switched to 'personal'" in verdicts[0]

    async def test_a_changed_verdict_appends_a_new_line(self, tmp_path: Path) -> None:
        cache = _cache(work=95.0, personal=10.0)
        app, _api, _store, _clock = wired_app(tmp_path, active_name="work", usage_cache=cache)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_auto(pilot)
            await settle_workers(pilot)
            # personal fills past work — the next evaluation stays put
            cache.save("personal", _usage(98.0))
            app.request_refresh()
            await settle_workers(pilot)
            text = "\n".join(_log_lines(app))
            assert "dry run: switched to 'personal'" in text
            assert "dry run: the active account already has the most headroom" in text
            # a stay verdict prints muted — only a move earns the accent
            log = app.screen.query_one("#event-log", RichLog)
            verdict = log.lines[2]
            assert strip_style_at(verdict, len(clock_stamp(app.now_s())) + 3) == DARK.muted

    async def test_no_live_login_reports_usage_unavailable(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_auto(pilot)
            await settle_workers(pilot)
            assert any(
                "dry run: usage unknown — cannot rank candidates" in line
                for line in _log_lines(app)
            )

    async def test_a_failing_evaluation_logs_the_error(self, tmp_path: Path) -> None:
        class _FailingSwitch:
            def execute(self, *_args: object, **_kwargs: object) -> object:
                raise RuntimeError("selection blew up")

        app, _api, _store, _clock = wired_app(tmp_path, switch=_FailingSwitch())
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_auto(pilot)
            await settle_workers(pilot)
            assert any("dry-run failed: selection blew up" in line for line in _log_lines(app))
            verdict = app.screen.query_one("#event-log", RichLog).lines[1]
            assert strip_style_at(verdict, len(clock_stamp(app.now_s())) + 3) == DARK.sev_warn

    async def test_the_decision_runs_in_a_labelled_worker(self, tmp_path: Path) -> None:
        app, _api, _store, clock = wired_app(tmp_path, active_name="work")
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_auto(pilot)
            await settle_workers(pilot)  # the mount-time decision drains first
            screen = app.screen
            captured: list[dict[str, object]] = []
            real_run_worker = screen.run_worker

            def spy(work: object, **kw: object) -> object:
                captured.append(kw)
                return real_run_worker(work, **kw)

            screen.run_worker = spy  # type: ignore[method-assign]
            clock.advance(1)
            app.request_refresh()
            await settle_workers(pilot)
            auto_workers = [kw for kw in captured if kw.get("group") == "auto"]
            assert len(auto_workers) == 1
            kw = auto_workers[0]
            description = kw.pop("description")
            assert kw == {
                "thread": True,
                "group": "auto",
                "name": "auto-dry-run",
                "exit_on_error": False,
                "exclusive": False,
            }
            # @work forwards an auto-built description alongside the kwargs the
            # call site used to own; pin it only to the method it wraps.
            assert description.startswith("_decide_blocking(")

    async def test_a_fresh_snapshot_does_not_queue_a_second_evaluation(
        self, tmp_path: Path
    ) -> None:
        # kick 1 parks inside execute; while it's parked a second snapshot
        # arrives — the single-flight guard must refuse a second worker.
        switch = _ParkingSwitch()
        app, _api, _store, clock = wired_app(tmp_path, active_name="work", switch=switch)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_auto(pilot)
            for _ in range(100):
                if switch.entered.is_set():
                    break
                await pilot.pause()
            clock.advance(1)
            app.request_refresh()
            for _ in range(100):
                snap = app.snapshot
                if snap is not None and snap.taken_at_s >= 1_000_001.0:
                    break
                await pilot.pause()
            switch.release.set()
            await settle_workers(pilot)
            assert switch.calls == 1

    async def test_a_late_result_on_a_popped_screen_is_dropped(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path, active_name="work")
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_auto(pilot)
            await settle_workers(pilot)
            screen = app.screen
            assert isinstance(screen, AutoScreen)
            log = app.screen.query_one("#event-log", RichLog)
            before = len(log.lines)
            await pilot.press("escape")
            await pilot.pause()
            screen._deciding = True
            screen._decision_done(SwitchResult(outcome="already-best", dry_run=True))
            assert screen._deciding is False  # the lane always frees
            assert len(log.lines) == before  # detached: nothing written
            assert isinstance(app.screen, DashboardScreen)


class TestThemeFlip:
    async def test_a_theme_change_repaints_summary_and_candidates(self, tmp_path: Path) -> None:
        cache = _cache(work=95.0, personal=20.0)
        app, _api, _store, _clock = wired_app(tmp_path, active_name="work", usage_cache=cache)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            await _open_auto(pilot)
            await settle_workers(pilot)
            app.apply_theme("light")
            await pilot.pause()
            assert "threshold 90%" in str(app.screen.query_one("#auto-summary", Static).content)
            assert "personal" in _candidates(app)
            assert str(_candidate_text(app).style) == MUTED_LIGHT
