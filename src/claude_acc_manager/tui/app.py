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

import gc
from collections.abc import Callable, Mapping
from typing import NamedTuple, Protocol, TypeVar

from textual import work
from textual.app import App
from textual.binding import Binding
from textual.notifications import SeverityLevel
from textual.reactive import reactive
from textual.timer import Timer
from textual.widget import Widget
from textual.worker import Worker, WorkerState

from claude_acc_manager.accounts.application.switch_message import switch_message
from claude_acc_manager.accounts.application.use_cases.collect_accounts_view import (
    AccountsView,
    AccountView,
    CollectAccountsView,
)
from claude_acc_manager.accounts.application.use_cases.quarantine_dead_lineage import (
    QuarantineDeadLineage,
)
from claude_acc_manager.accounts.application.use_cases.remove_account import RemoveAccount
from claude_acc_manager.accounts.application.use_cases.set_account_enabled import (
    SetAccountEnabled,
)
from claude_acc_manager.accounts.application.use_cases.switch_account import (
    SwitchAccount,
    SwitchResult,
)
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.settings.application.use_cases.list_settings import ListSettings
from claude_acc_manager.settings.application.use_cases.load_settings import LoadSettings
from claude_acc_manager.settings.application.use_cases.set_setting import SetSetting
from claude_acc_manager.settings.domain.settings_spec import (
    EffectiveSetting,
    SettingSpec,
)
from claude_acc_manager.tui.account_list import SwitchScreen, WatchScreen
from claude_acc_manager.tui.autoview import AutoScreen
from claude_acc_manager.tui.dashboard import DashboardScreen
from claude_acc_manager.tui.formatting import format_duration
from claude_acc_manager.tui.modals import ConfirmModal
from claude_acc_manager.tui.palette import CamCommandsProvider
from claude_acc_manager.tui.settings_screen import SettingsScreen
from claude_acc_manager.tui.theme import CAM_DARK, CAM_LIGHT
from claude_acc_manager.tui.throbber import LoadingBar
from claude_acc_manager.usage.application.ports import ClockPort
from claude_acc_manager.usage.application.use_cases.fetch_account_usage import (
    FetchAccountUsage,
)
from claude_acc_manager.usage.domain.services.headroom import account_headroom

# PEP 695 generics (`def f[T]`) parse only on 3.12+; the supported floor is
# 3.11, so the three _action_* helpers share this plain TypeVar instead.
_T = TypeVar("_T")


class ActionToast(NamedTuple):
    """A finished action's toast: message plus severity."""

    message: str
    severity: SeverityLevel


def _switch_toast(result: SwitchResult) -> ActionToast:
    """Switches toast info on a move, warning on a non-move outcome."""
    return ActionToast(
        switch_message(result),
        "information" if result.outcome == "switched" else "warning",
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
    def set_enabled(self) -> SetAccountEnabled:
        """Flips an account's participation in automatic picks."""
        ...

    @property
    def remove(self) -> RemoveAccount:
        """Drops a registry entry and deletes its stored login dir."""
        ...

    @property
    def switch(self) -> SwitchAccount:
        """Moves the live login to another account, transactionally."""
        ...

    @property
    def usage_clock(self) -> ClockPort:
        """The clock the view stamps ``taken_at_s`` with."""
        ...

    @property
    def list_settings(self) -> ListSettings:
        """One ``EffectiveSetting`` row per spec key, in spec order."""
        ...

    @property
    def load_settings(self) -> LoadSettings:
        """The forgiving section read — clamped effective ``AutoSettings``."""
        ...

    @property
    def set_setting(self) -> SetSetting:
        """Strict-validate one ``dotted.key`` string, then persist it."""
        ...


class CamApp(App[None]):
    """cam interactive dashboard."""

    TITLE = "cam"
    CSS_PATH = "cam.tcss"
    # The palette's key (textual's ctrl+p stays as a hidden fallback below);
    # per-account switch hits live in palette.py.
    COMMAND_PALETTE_BINDING = "ctrl+space"
    COMMANDS = {CamCommandsProvider}
    # Under 100 columns the screen carries -narrow; ≥100 carries -wide.
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (100, "-wide")]
    BINDING_GROUP_TITLE = "cam"
    BINDINGS = [
        Binding(
            "f1",
            "toggle_help_panel",
            "Help",
            tooltip="Show this screen's keys and what it does.",
            priority=True,
        ),
        # COMMAND_PALETTE_BINDING won't auto-bind once any command_palette
        # action exists, so both keys are declared: ctrl+space collapses to
        # NUL in some terminals and ctrl+p is textual's shipped default.
        Binding(
            "ctrl+space",
            "command_palette",
            show=False,
            tooltip="Search every command — including switch hits.",
        ),
        Binding(
            "ctrl+p",
            "command_palette",
            show=False,
            tooltip="Search every command — including switch hits.",
        ),
        Binding(
            "ctrl+t", "toggle_theme", "Theme", tooltip="Flip between the dark and light theme."
        ),
    ]

    POLL_INTERVAL_S = 3.0
    # Snapshot age stays hidden while polling is healthy (age never exceeds
    # ~POLL_INTERVAL_S); past this it surfaces as a staleness alarm. 60s also
    # keeps format_duration in whole minutes, so the note never ticks per
    # second.
    SNAPSHOT_AGE_NOTE_S = 60.0
    # Scroll-heavy screen churn — a GC pass mid-scroll hitches frames.
    PAUSE_GC_ON_SCROLL = True

    snapshot: reactive[AccountsView | None] = reactive(None)
    refresh_status: reactive[str] = reactive("")
    busy: reactive[bool] = reactive(False)
    terminal_title_blink: reactive[bool] = reactive(False)
    # Drawn as a tick on every usage bar; seeded from settings on mount and
    # live-updated by apply_setting so a TUI edit repaints immediately.
    threshold_pct: reactive[float] = reactive(90.0)

    # ~3s attention window at a half-second half-period.
    TITLE_BLINK_TICKS = 6
    BLINK_INTERVAL_S = 0.5

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
        self._title_blink_timer: Timer | None = None
        self._title_blink_ticks = 0
        self.theme_name = "dark"

    def on_mount(self) -> None:
        """Register themes, push the landing screen, and start the poll tick."""
        # Freeze the startup heap out of the collection set — the scroll-heavy
        # screens churn enough young objects without rescanning these.
        gc.freeze()  # pragma: no mutate — GC tuning has no Pilot-observable seam
        self.register_theme(CAM_DARK)
        self.register_theme(CAM_LIGHT)
        # We own the theme; $TEXTUAL_THEME is intentionally not honoured.
        self.theme = f"cam-{self.theme_name}"
        self.threshold_pct = float(self._use_cases.load_settings.execute().threshold)
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
        self._refresh_blocking(generation)

    @work(  # pragma: no mutate — thread=True keeps the fetch pass off the UI loop
        thread=True,
        exit_on_error=False,
        group="refresh",
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

    def action_open_switch(self) -> None:
        """`s`/menu — stack the switch list over the dashboard, once."""
        if not isinstance(self.screen, SwitchScreen):
            self.push_screen(SwitchScreen())

    def action_open_auto(self) -> None:
        """`g`/menu — stack the dry-run auto preview over the dashboard."""
        if not isinstance(self.screen, AutoScreen):
            self.push_screen(AutoScreen())

    def action_open_settings(self) -> None:
        """menu/palette — push the generated settings editor, once."""
        if not isinstance(self.screen, SettingsScreen):
            self.push_screen(SettingsScreen())

    def settings_rows(self) -> tuple[EffectiveSetting, ...]:
        """The editor's data feed — spec-ordered effective values.

        Example:
            ``app.settings_rows()[0].spec.dotted == "autoswitch.threshold"``
        """
        return self._use_cases.list_settings.execute()

    def apply_setting(self, spec: SettingSpec, raw_value: str) -> bool:
        """Strict-validate and persist one key; ``False`` + toast on rejects.

        A good ``autoswitch.threshold`` write moves ``threshold_pct`` now —
        the bar tick is the same session, not next launch.

        Example:
            ``app.apply_setting(spec, "80")`` → ``settings.json`` gains 80.0
        """
        try:
            value = self._use_cases.set_setting.execute(spec.dotted, raw_value)
        except ValueError as exc:
            self.notify(str(exc), title=spec.dotted, severity="error")
            return False
        if spec.field == "threshold":
            self.threshold_pct = float(value)
        return True

    def headroom_map(self) -> dict[str, float | None]:
        """Per-name measured headroom over the current snapshot.

        ``None`` means unknown — never exhausted — the same mapping the
        ``best`` strategy and the auto preview's dry-run both consume.
        """
        snap = self.snapshot
        return {
            row.account.name.value: account_headroom(row.usage.last_good)
            for row in (snap.accounts if snap else ())
        }

    def dry_run_best(self, headroom: Mapping[str, float | None]) -> SwitchResult:
        """Simulated ``best`` selection — the auto preview's decision feed.

        ``dry_run=True`` never writes, but the use case still reads ports
        (live slot, parked dirs); callers run it off the UI loop.
        """
        return self._use_cases.switch.execute(strategy="best", headroom=headroom, dry_run=True)

    # -- mutating actions (single-flight, off-thread) ------------------------

    def do_switch(self, name: str) -> None:
        """Switch the live login to *name*; the outcome arrives as a toast.

        Example:
            ``app.do_switch("personal")`` → toast ``switched to 'personal' …``
        """
        self._run_action(
            f"switch to {name}",
            lambda: self._use_cases.switch.execute(AccountName(name)),
            _switch_toast,
            "switch failed",
        )

    def action_switch_best(self) -> None:
        """`b` — strategy=``best`` over the snapshot's cached headroom."""
        self._run_action(
            "switch (best)",
            lambda: self._use_cases.switch.execute(strategy="best", headroom=self.headroom_map()),
            _switch_toast,
            "switch failed",
        )

    def do_toggle_enabled(self, name: str) -> None:
        """Flip *name*'s enabled flag; the toast names the new state.

        Example:
            ``app.do_toggle_enabled("work")`` → toast ``disabled account 'work'``
        """
        row = self._snapshot_row(name)
        if row is None:
            self.notify(f"no account named {name!r}", severity="warning")
            return
        enabled = not row.account.enabled
        self._run_action(
            f"toggle {name}",
            lambda: self._use_cases.set_enabled.execute(AccountName(name), enabled),
            lambda account: ActionToast(
                f"{'enabled' if account.enabled else 'disabled'} account {name!r}",
                "information",
            ),
            "toggle failed",
        )

    @work(  # pragma: no mutate — exit_on_error=False keeps a modal error silent, not fatal
        exit_on_error=False,
        group="modal",
        name="confirm-remove",
    )
    async def confirm_remove(self, name: str) -> None:
        """Ask before deleting *name* — the modal answers True only on yes.

        Example:
            ``app.confirm_remove("work")`` → "Remove account 'work' (…)?"
        """
        # push_screen_wait is worker-only; the await parks this lane until
        # dismiss while the caller's handlers keep running.
        if await self.push_screen_wait(
            ConfirmModal(
                self._remove_message(name),
                title="Remove account",
                yes_label="Remove",
            )
        ):
            self.do_remove(name)

    def _remove_message(self, name: str) -> str:
        """The confirm body; removing the live account leaves it unmanaged."""
        row = self._snapshot_row(name)
        email = ""
        if row is not None and row.account.email:
            email = f" ({row.account.email})"
        lines = [
            f"Remove account {name!r}{email}?",
            "",
            "Its stored login directory is deleted.",
        ]
        if row is not None and row.is_active:
            lines.append(f"{name!r} is the live account — the login stays, unmanaged.")
        return "\n".join(lines)

    def do_remove(self, name: str) -> None:
        """Delete *name*'s registry entry and parked login dir.

        Example:
            ``app.do_remove("work")`` → toast ``removed account 'work'``
        """
        self._run_action(
            f"remove {name}",
            lambda: self._use_cases.remove.execute(AccountName(name)),
            lambda _result: ActionToast(f"removed account {name!r}", "information"),
            "remove failed",
        )

    def _snapshot_row(self, name: str) -> AccountView | None:
        """The snapshot row for *name*, or None when absent/unsnapshotted."""
        snap = self.snapshot
        return next(
            (r for r in (snap.accounts if snap else ()) if r.account.name.value == name),
            None,
        )

    def _run_action(
        self,
        label: str,
        call: Callable[[], _T],
        toast: Callable[[_T], ActionToast],
        failure: str,
    ) -> None:
        """Single-flight a mutating action in a thread worker."""
        if self.busy:
            self.notify("another action is still running", severity="warning")
            return
        self.busy = True
        self._action_blocking(label, call, toast, failure)

    @work(  # pragma: no mutate — thread=True keeps the mutation off the UI loop
        thread=True,
        exit_on_error=False,
        group="action",
        name="action",
    )
    def _action_blocking(
        self,
        label: str,
        call: Callable[[], _T],
        toast: Callable[[_T], ActionToast],
        failure: str,
    ) -> None:
        """Run the use case off the event loop, then post the outcome.

        ``label`` rides the worker's auto-built description (textual reprs
        the decorated args) — the per-action identity ``name=`` carried when
        the call site owned ``run_worker``; decorator kwargs are static on
        our textual pin.
        """
        try:
            result: _T | Exception = call()
        except Exception as exc:
            result = exc
        self.call_from_thread(self._action_done, result, toast, failure)

    def _action_done(
        self,
        result: _T | Exception,
        toast: Callable[[_T], ActionToast],
        failure: str,
    ) -> None:
        """Free the lane, repaint from the post-action world, and toast."""
        self.busy = False
        self.request_refresh()
        self._blink_terminal_title()
        if isinstance(result, Exception):
            self.notify(f"{failure}: {result}", severity="error", timeout=8)
            return
        done = toast(result)
        self.notify(done.message, severity=done.severity)

    def get_loading_widget(self) -> Widget:
        """The branded ``.loading`` cover — the palette sweep, not stock dots."""
        return LoadingBar()

    # -- terminal title ---------------------------------------------------------

    def update_terminal_title(self) -> None:
        r"""Write ``cam — <screen>`` to the terminal's window title (OSC 0).

        Textual never emits one itself — ``driver.write`` is the same seam
        ``copy_to_clipboard`` uses for its OSC 52 escape.

        Example:
            on the dashboard → ``\\033]0;cam — dashboard\\007``
        """
        screen_title = self.screen.title or ""
        title = f"{self.title} — {screen_title}" if screen_title else self.title
        if self.terminal_title_blink:
            title = f"* {title}"
        driver = self._driver
        if driver is not None:
            driver.write(f"\033]0;{title}\007")

    def watch_terminal_title_blink(self) -> None:
        """Rewrite the title each half-cycle so the marker visibly alternates."""
        self.update_terminal_title()

    def _blink_terminal_title(self) -> None:
        """Arm the ~3s attention blink — only when the window lacks focus."""
        if self.app_focus:
            return
        self._title_blink_ticks = self.TITLE_BLINK_TICKS
        self.terminal_title_blink = True
        if self._title_blink_timer is None:
            self._title_blink_timer = self.set_interval(
                self.BLINK_INTERVAL_S, self._blink_title_step
            )

    def _blink_title_step(self) -> None:
        """One half-second toggle; the last tick clears marker and timer."""
        self._title_blink_ticks -= 1
        if self._title_blink_ticks <= 0:
            timer = self._title_blink_timer
            self._title_blink_timer = None
            if timer is not None:
                timer.stop()
            self.terminal_title_blink = False
            return
        self.terminal_title_blink = not self.terminal_title_blink

    # -- theme ----------------------------------------------------------------

    def apply_theme(self, name: str) -> None:
        """Switch to a registered ``cam-*`` theme by short name."""
        self.theme_name = name
        self.theme = f"cam-{name}"

    def action_toggle_theme(self) -> None:
        """`ctrl+t` flips dark ↔ light for the session (not persisted)."""
        self.apply_theme("light" if self.theme_name == "dark" else "dark")
        self.notify(f"Theme: {self.theme_name}")

    def action_toggle_help_panel(self) -> None:
        """`f1` opens the help panel; a second press closes it."""
        if self.screen.query("HelpPanel"):
            self.action_hide_help_panel()
        else:
            self.action_show_help_panel()
