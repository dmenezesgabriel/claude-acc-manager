"""The cam Textual application.

Owns the snapshot poll loop and every mutating action, so the dashboard,
the watch view, and the auto preview all drive the same code paths.
Blocking use-case work always runs in thread workers — the UI loop never
touches file locks, credentials, or the network.

All timing reads go through the injected ``usage_clock`` — the same clock
the view collection stamps ``taken_at_s`` with — so staleness notes and
test fakes share one time base.
"""

from __future__ import annotations

from functools import partial
from typing import Protocol

from textual.app import App
from textual.binding import Binding
from textual.reactive import reactive
from textual.worker import Worker, WorkerState

from claude_acc_manager.accounts.application.use_cases.collect_accounts_view import (
    AccountsView,
    CollectAccountsView,
)
from claude_acc_manager.accounts.application.use_cases.quarantine_dead_lineage import (
    QuarantineDeadLineage,
)
from claude_acc_manager.tui.dashboard import DashboardScreen, WatchScreen
from claude_acc_manager.tui.formatting import format_duration
from claude_acc_manager.tui.theme import CAM_DARK, CAM_LIGHT
from claude_acc_manager.usage.application.ports import ClockPort
from claude_acc_manager.usage.application.use_cases.fetch_account_usage import (
    FetchAccountUsage,
)


class TuiUseCases(Protocol):
    """The use-case surface the TUI consumes — satisfied by cli ``UseCases``.

    Declared structurally so the TUI never imports the other transport (the
    import-linter `tui` contract forbids ``claude_acc_manager.cli``). The
    attributes are properties — read-only — so the frozen ``UseCases``
    dataclass satisfies the protocol without loosening its immutability.
    """

    @property
    def collect_view(self) -> CollectAccountsView:
        """The one-pass dashboard read model."""
        ...

    @property
    def fetch_usage(self) -> FetchAccountUsage:
        """The gated per-account usage fetch."""
        ...

    @property
    def quarantine_dead_lineage(self) -> QuarantineDeadLineage:
        """Tombstones a refresh-token lineage the provider rejected."""
        ...

    @property
    def usage_clock(self) -> ClockPort:
        """The clock the view stamps ``taken_at_s`` with."""
        ...


class CamApp(App[None]):
    """cam interactive dashboard."""

    TITLE = "cam"
    CSS_PATH = "cam.tcss"
    # No command palette: actions live in the dashboard's nested menu, in
    # their own context — not in a global searchable list.
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [Binding("ctrl+t", "toggle_theme", "Theme")]

    POLL_INTERVAL_S = 3.0
    # Snapshot age stays hidden while polling is healthy (age never exceeds
    # ~POLL_INTERVAL_S); past this it surfaces as a staleness alarm. 60s also
    # keeps format_duration in whole minutes, so the note never ticks per
    # second.
    SNAPSHOT_AGE_NOTE_S = 60.0

    snapshot: reactive[AccountsView | None] = reactive(None)
    refresh_status: reactive[str] = reactive("")
    busy: reactive[bool] = reactive(False)

    def __init__(self, use_cases: TuiUseCases, *, start: str = "dashboard") -> None:
        """Store the injected use cases; ``start`` picks the landing screen."""
        super().__init__()
        self._use_cases = use_cases
        self._start = start  # "dashboard" | "watch" (`cam watch`)
        self._refreshing = False
        self._refresh_started_at: float | None = None
        self._refresh_generation = 0
        self._applied_generation = 0
        self._last_refresh_error = ""
        self.theme_name = "dark"
        # The auto-switch threshold, drawn as a tick on the bars everywhere —
        # fixed at the documented default until persisted settings land (M9).
        self.threshold_pct: float = 90.0

    def on_mount(self) -> None:
        """Register themes, push the landing screen, and start the poll tick."""
        self.register_theme(CAM_DARK)
        self.register_theme(CAM_LIGHT)
        # We own the theme; $TEXTUAL_THEME is intentionally not honoured.
        self.theme = f"cam-{self.theme_name}"
        self.push_screen(DashboardScreen())
        if self._start == "watch":
            # Stacked over the dashboard so Esc lands there, not on exit.
            self.push_screen(WatchScreen())
        self.set_interval(self.POLL_INTERVAL_S, self._tick)
        # 1s wall-clock cadence so staleness notes age without an event —
        # the Pilot suite observes _update_refresh_status synchronously.
        self.set_interval(1.0, self._update_refresh_status)  # pragma: no mutate
        self._tick()  # pragma: no mutate — eager first poll; the interval owns cadence

    def now_s(self) -> float:
        """The injected clock — every timestamp the view carries shares it."""
        return self._use_cases.usage_clock.now_epoch_s()

    # -- snapshot poll loop -------------------------------------------------

    def request_refresh(self) -> None:
        """Queue a poll tick now — the per-account gates decide what fetches."""
        self._tick()

    def _tick(self) -> None:
        """Start one refresh lane; single-flight keeps ticks from stacking."""
        if self._refreshing:
            return
        self._refreshing = True
        self._refresh_started_at = self.now_s()
        self._refresh_generation += 1
        generation = self._refresh_generation
        self._update_refresh_status()
        self.run_worker(
            partial(self._refresh_blocking, generation),
            thread=True,  # pragma: no mutate — never block the UI loop on I/O
            group="refresh",
            exit_on_error=False,
            name="snapshot-refresh",
        )

    def _refresh_blocking(self, generation: int) -> None:
        """Collect → gated fetch pass → re-collect, then post the frame.

        The fetch pass inherits FetchAccountUsage's persisted-plan gate, so a
        3s poller can never storm the endpoint. Quarantined lineages are
        skipped; a newly dead one is tombstoned in place.
        """
        for row in self._use_cases.collect_view.execute().accounts:
            if row.is_quarantined:
                continue
            report = self._use_cases.fetch_usage.execute(
                row.account.name.value, is_active=row.is_active
            )
            if report.permanent_auth_error:
                self._use_cases.quarantine_dead_lineage.execute(row.account.name)
        view = self._use_cases.collect_view.execute()
        self.call_from_thread(self._apply_snapshot, generation, view)

    def _apply_snapshot(self, generation: int, view: AccountsView) -> None:
        """Apply a worker result; a lower generation is stale and dropped."""
        self._refreshing = False
        self._refresh_started_at = None
        self._last_refresh_error = ""
        if generation >= self._applied_generation:
            self._applied_generation = generation
            self.snapshot = view
        self._update_refresh_status()

    def _update_refresh_status(self) -> None:
        parts: list[str] = []
        if self.snapshot is not None:
            # max() clamps clock skew below the 60s note floor — always
            # invisible, so mutants of the floor are equivalent by design.
            age = max(0.0, self.now_s() - self.snapshot.taken_at_s)  # pragma: no mutate
            if age >= self.SNAPSHOT_AGE_NOTE_S:
                parts.append(f"snapshot {format_duration(age)} ago")
        if self._refreshing and self._refresh_started_at is not None:
            elapsed = self.now_s() - self._refresh_started_at
            if elapsed >= self.POLL_INTERVAL_S:
                parts.append(f"refreshing {format_duration(elapsed)}")
        self.refresh_status = " · ".join(parts)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """A failed refresh clears the lane and surfaces once per new error."""
        # textual types StateChanged.worker as Worker[Any] upstream — narrow
        # the generic locally so the group/error reads stay checked.
        worker: Worker[object] = event.worker  # type: ignore[reportUnknownMemberType]
        if event.state is not WorkerState.ERROR or worker.group != "refresh":
            return
        self._refreshing = False
        self._refresh_started_at = None
        self._update_refresh_status()
        msg = str(worker.error)
        if msg == self._last_refresh_error:
            return
        self._last_refresh_error = msg
        self.notify(f"Refresh failed: {msg}", severity="warning", timeout=6)

    # -- navigation ----------------------------------------------------------

    def action_refresh_full(self) -> None:
        """`f` asks for a pass now; the per-account plan still caps fetches."""
        self.request_refresh()
        self.notify("Refreshing usage…", timeout=2)

    def action_open_watch(self) -> None:
        """`w`/menu — stack the watch monitor over the dashboard, once."""
        if not isinstance(self.screen, WatchScreen):
            self.push_screen(WatchScreen())

    # -- theme ----------------------------------------------------------------

    def apply_theme(self, name: str) -> None:
        """Switch to a registered ``cam-*`` theme by short name."""
        self.theme_name = name
        self.theme = f"cam-{name}"

    def action_toggle_theme(self) -> None:
        """`ctrl+t` flips dark ↔ light for the session (persistence is M9)."""
        self.apply_theme("light" if self.theme_name == "dark" else "dark")
        self.notify(f"Theme: {self.theme_name}")
