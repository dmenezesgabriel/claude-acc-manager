"""The auto-switch preview — a dry-run view of the auto engine's pick.

The screen renders the active account's card, the candidates ``best``
would rank, and a decision log fed by the real
``switch.execute(strategy="best", dry_run=True)`` path — re-evaluated on
each applied snapshot, deduped so only outcome changes print. The fixed
DRY-RUN badge is the contract: nothing on this screen moves the live
login. The engine itself is the ``cam auto`` loop (``auto_tick``,
cooldowns, SIGTERM).
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from rich.text import Text
from textual import getters
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, RichLog, Static

from claude_acc_manager.accounts.application.ports import SwitchResult
from claude_acc_manager.accounts.application.switch_message import switch_message
from claude_acc_manager.accounts.application.use_cases.collect_accounts_view import (
    AccountsView,
    AccountView,
)
from claude_acc_manager.tui.formatting import clock_stamp
from claude_acc_manager.tui.theme import Palette
from claude_acc_manager.tui.widgets import AccountsPanel
from claude_acc_manager.usage.domain.services.poll_policy import binding_pct

if TYPE_CHECKING:
    from claude_acc_manager.tui.app import CamApp


class AutoScreen(Screen[None]):
    """Preview of what a ``best``-strategy auto-switch would decide."""

    BINDINGS = [
        Binding("escape,q", "back", "Back"),
        Binding("f", "app.refresh_full", "Refresh", show=False),
    ]

    app: CamApp

    event_log = getters.query_one("#event-log", RichLog)
    auto_summary = getters.query_one("#auto-summary", Static)
    candidates = getters.query_one("#candidates", Static)

    def __init__(self) -> None:
        """Single-flight guard plus the last logged verdict for dedupe."""
        super().__init__()
        self._deciding = False
        self._last_decision = ""

    def compose(self) -> ComposeResult:
        """Active card on top, then the badge/summary/candidates, then the log."""
        yield AccountsPanel(show_minis=False, id="auto-active-panel")
        with Vertical(id="auto-top"):
            with Horizontal(id="auto-title-row"):
                yield Static(" DRY-RUN ", id="mode-badge", classes="dry")
                yield Static(id="auto-summary")
            yield Static(id="candidates")
        yield RichLog(id="event-log", wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        """Paint the static chrome, then hook the snapshot and theme watches."""
        self._update_summary()
        log = self.event_log
        log.write(
            Text(
                "— dry-run preview · decisions are simulated —",
                style=Palette.from_theme(self.app.current_theme).muted,
            )
        )
        self.watch(self.app, "snapshot", self._on_snapshot)
        self.watch(self.app, "theme", self._on_theme)

    def action_back(self) -> None:
        """Esc/q pop back to whatever pushed this screen."""
        self.app.pop_screen()

    def _update_summary(self) -> None:
        """The one-line caption: strategy, fixed threshold, poll cadence."""
        text = Text()
        text.append("auto-switch · ")
        text.append(f"threshold {self.app.threshold_pct:g}%")
        text.append(f" · poll every {self.app.POLL_INTERVAL_S:g}s")
        self.auto_summary.update(text)

    def _on_theme(self, *_args: object) -> None:
        """Repaint palette-baked renderables on a theme flip."""
        self._update_summary()
        snap = self.app.snapshot
        if snap is not None:
            self._render_candidates(snap)

    def _on_snapshot(self, snap: AccountsView | None) -> None:
        """Repaint the ranking and re-evaluate the decision per frame."""
        if snap is None:
            return
        self._render_candidates(snap)
        self._kick_decision()

    def _render_candidates(self, snap: AccountsView) -> None:
        """Repaint the ranked-candidates block for one applied snapshot."""
        self.candidates.update(self._candidates_text(snap))

    # -- candidates -----------------------------------------------------------

    def _candidates_text(self, snap: AccountsView) -> Text:
        """Every non-active account, best pick first, markers for the rest.

        Ranking by ``binding_pct`` ascending is ranking by remaining
        headroom descending — the same order ``best`` would pick in, so the
        display can never disagree with the logged decision.
        """
        palette = Palette.from_theme(self.app.current_theme)
        rows = [row for row in snap.accounts if not row.is_active]
        text = Text("Next best", style=palette.muted)
        if not rows:
            text.append("\n  no other accounts", style=palette.muted)
            return text
        measured: list[tuple[float, Text]] = []
        quiet: list[Text] = []
        for row in rows:
            marker = _skip_marker(row)
            if marker is not None:
                quiet.append(_candidate_line(row, marker, palette.muted))
                continue
            pct = binding_pct(row.usage.last_good)
            if pct is None:
                quiet.append(_candidate_line(row, "usage unknown", palette.muted))
                continue
            measured.append((pct, _candidate_line(row, f"{pct:3.0f}% used", palette.severity(pct))))
        # key= keeps registry order on a tie — Text isn't orderable.
        for _pct, line in sorted(measured, key=lambda t: t[0]):
            text.append(line)
        for line in quiet:
            text.append(line)
        return text

    # -- decision log -----------------------------------------------------------

    def _kick_decision(self) -> None:
        """One dry-run evaluation in flight at a time, off the UI loop."""
        if self._deciding:
            return
        self._deciding = True
        headroom = self.app.headroom_map()
        self.run_worker(
            partial(self._decide_blocking, headroom),
            thread=True,  # pragma: no mutate — the pick reads disk slots
            group="auto",
            exit_on_error=False,
            name="auto-dry-run",
        )

    def _decide_blocking(self, headroom: dict[str, float | None]) -> None:
        """Run the real best-selection in dry-run, then post the verdict."""
        try:
            result: SwitchResult | Exception = self.app.dry_run_best(headroom)
        except Exception as exc:
            result = exc
        self.app.call_from_thread(self._decision_done, result)

    def _decision_done(self, result: SwitchResult | Exception) -> None:
        """Free the lane and log the verdict — only when it changed."""
        self._deciding = False
        if not self.is_attached:
            return  # the screen popped while the worker was in flight
        palette = Palette.from_theme(self.app.current_theme)
        if isinstance(result, Exception):
            message = f"dry-run failed: {result}"
            style = palette.sev_warn
        else:
            message = switch_message(result)
            style = palette.accent if result.outcome == "switched" else palette.muted
        if message == self._last_decision:
            return
        self._last_decision = message
        line = Text()
        line.append(f"{clock_stamp(self.app.now_s())}  ", style=palette.muted)
        line.append(message, style=style)
        self.event_log.write(line)


def _skip_marker(row: AccountView) -> str | None:
    """Why ``best`` can never pick this account, or None when it can."""
    if not row.account.enabled:
        return "(disabled)"
    if row.is_quarantined:
        return "⚠ quarantined"
    if not row.has_credentials:
        return "no stored login"
    return None


def _candidate_line(row: AccountView, suffix: str, style: str) -> Text:
    r"""``\n  name (email)  <suffix>`` — one ranked or marked candidate row."""
    account = row.account
    line = Text()
    line.append(f"\n  {account.name.value}")
    if account.email:
        line.append(f" ({account.email})")
    line.append(f"  {suffix}", style=style)
    return line
