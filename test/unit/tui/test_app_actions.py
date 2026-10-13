"""CamApp Pilot tests — account actions, worker failure, update notice.

The dashboard's mutating surface — switches, removes, enables — plus what
happens when a worker dies mid-flight, through the same worker-draining
harness as the lifecycle tests.
"""

import threading
from pathlib import Path

from support.in_memory_settings import emails_visible_settings
from support.tui_app import settle_workers, wired_app
from support.use_cases import make_check_update
from textual.widgets import Button, Static

from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.tui.modals import ConfirmModal
from claude_acc_manager.usage.application.use_cases.fetch_account_usage import (
    FetchAccountUsage,
    UsageReport,
)


class _RaisingFetchUsage(FetchAccountUsage):
    """Fails every fetch — exercises the refresh worker's error path."""

    def __init__(self) -> None:
        """No ports needed — execute raises before it can reach them."""

    def execute(self, account_key: str, is_active: bool) -> UsageReport:
        """Raise unconditionally."""
        raise RuntimeError("boom")


class _RaisingFetchUsage(FetchAccountUsage):
    """Fails every fetch — exercises the refresh worker's error path."""

    def __init__(self) -> None:
        """No ports needed — execute raises before it can reach them."""

    def execute(self, account_key: str, is_active: bool) -> UsageReport:
        """Raise unconditionally."""
        raise RuntimeError("boom")


class TestAccountActions:
    """Toggle/remove share the switch lane: busy-gated, off-thread, toasts."""

    async def test_toggle_disables_the_named_account(self, tmp_path: Path) -> None:
        notes: list[tuple[object, dict[str, object]]] = []
        captured: list[dict[str, object]] = []
        app, _api, store, _clock = wired_app(tmp_path)
        app.notify = lambda message, **kw: notes.append((message, kw))
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            original = app.run_worker
            app.run_worker = lambda work, **kw: (  # type: ignore[method-assign]
                captured.append(kw),
                original(work, **kw),
            )[1]
            app.actions.toggle_enabled("personal")
            await settle_workers(pilot)
            action_kwargs = [kw for kw in captured if kw["group"] == "action"]
            # the runner names each action worker with its per-call label
            assert [kw["name"] for kw in action_kwargs] == ["toggle personal"]
            account = store.get(AccountName("personal"))
            assert account is not None and account.enabled is False
            assert notes == [("disabled account 'personal'", {"severity": "information"})]
            assert app.busy is False

    async def test_toggle_re_enables_a_disabled_account(self, tmp_path: Path) -> None:
        notes: list[tuple[object, dict[str, object]]] = []
        app, _api, store, _clock = wired_app(tmp_path)
        store.set_enabled(AccountName("personal"), False)
        app.notify = lambda message, **kw: notes.append((message, kw))
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app.actions.toggle_enabled("personal")
            await settle_workers(pilot)
            account = store.get(AccountName("personal"))
            assert account is not None and account.enabled is True
            assert notes == [("enabled account 'personal'", {"severity": "information"})]

    async def test_toggle_an_unknown_account_warns_without_a_worker(self, tmp_path: Path) -> None:
        notes: list[tuple[object, dict[str, object]]] = []
        app, _api, _store, _clock = wired_app(tmp_path)
        app.notify = lambda message, **kw: notes.append((message, kw))
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app.actions.toggle_enabled("ghost")
            await pilot.pause()
            assert notes == [("no account named 'ghost'", {"severity": "warning"})]
            assert app.busy is False

    async def test_toggle_before_the_first_snapshot_warns_without_a_worker(
        self, tmp_path: Path
    ) -> None:
        # the closed collect gate parks the mount refresh — snapshot stays
        # None, so the row lookup has no rows to search at all
        gate = threading.Event()
        notes: list[tuple[object, dict[str, object]]] = []
        app, _api, _store, _clock = wired_app(tmp_path, collect_gate=gate)
        app.notify = lambda message, **kw: notes.append((message, kw))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.snapshot is None
            app.actions.toggle_enabled("work")
            await pilot.pause()
            assert notes == [("no account named 'work'", {"severity": "warning"})]
            assert app.busy is False
            gate.set()
            await settle_workers(pilot)

    async def test_a_failed_toggle_surfaces_the_error(self, tmp_path: Path) -> None:
        # a stale snapshot can name an account the store no longer has —
        # set_enabled raises KeyError and the lane reports it
        notes: list[tuple[object, dict[str, object]]] = []
        app, _api, store, _clock = wired_app(tmp_path)
        app.notify = lambda message, **kw: notes.append((message, kw))
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            store.remove(AccountName("personal"))
            app.actions.toggle_enabled("personal")  # the row is still in the snapshot
            await settle_workers(pilot)
            assert notes == [("toggle failed: 'personal'", {"severity": "error", "timeout": 8})]

    async def test_remove_drops_the_account(self, tmp_path: Path) -> None:
        notes: list[tuple[object, dict[str, object]]] = []
        captured: list[dict[str, object]] = []
        app, _api, store, _clock = wired_app(tmp_path)
        app.notify = lambda message, **kw: notes.append((message, kw))
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            original = app.run_worker
            app.run_worker = lambda work, **kw: (  # type: ignore[method-assign]
                captured.append(kw),
                original(work, **kw),
            )[1]
            app.actions.remove("personal")
            await settle_workers(pilot)
            action_kwargs = [kw for kw in captured if kw["group"] == "action"]
            # the runner names each action worker with its per-call label
            assert [kw["name"] for kw in action_kwargs] == ["remove personal"]
            assert store.get(AccountName("personal")) is None
            assert notes == [("removed account 'personal'", {"severity": "information"})]

    async def test_a_failed_remove_surfaces_the_error(self, tmp_path: Path) -> None:
        notes: list[tuple[object, dict[str, object]]] = []
        app, _api, _store, _clock = wired_app(tmp_path)
        app.notify = lambda message, **kw: notes.append((message, kw))
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app.actions.remove("ghost")
            await settle_workers(pilot)
            assert notes == [("remove failed: 'ghost'", {"severity": "error", "timeout": 8})]

    async def test_confirm_remove_only_runs_on_yes(self, tmp_path: Path) -> None:
        app, _api, store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app.actions.confirm_remove("personal")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmModal)
            await pilot.press("n")
            await pilot.pause()
            assert store.get(AccountName("personal")) is not None
            app.actions.confirm_remove("personal")
            await pilot.pause()
            await pilot.press("y")
            await settle_workers(pilot)
            assert store.get(AccountName("personal")) is None

    async def test_the_remove_prompt_names_and_warns_on_active(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(
            tmp_path, active_name="work", settings=emails_visible_settings(tmp_path)
        )
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app.actions.confirm_remove("work")
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, ConfirmModal)
            title = str(modal.query_one(".modal-title", Static).content)
            body = str(modal.query_one(".modal-body", Static).content)
            assert title == "Remove account"
            assert str(modal.query_one("#yes", Button).label) == "Remove"
            assert body == (
                "Remove account 'work' (work@example.com)?\n\n"
                "Its stored login directory is deleted.\n"
                "'work' is the live account — the login stays, unmanaged."
            )

    async def test_the_remove_prompt_hides_the_email_by_default(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(tmp_path, active_name="work")
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app.actions.confirm_remove("work")
            await pilot.pause()
            body = str(app.screen.query_one(".modal-body", Static).content)
            assert body.startswith("Remove account 'work'?")
            assert "example.com" not in body

    async def test_the_remove_prompt_stays_plain_for_others(self, tmp_path: Path) -> None:
        app, _api, _store, _clock = wired_app(
            tmp_path, active_name="work", settings=emails_visible_settings(tmp_path)
        )
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app.actions.confirm_remove("personal")
            await pilot.pause()
            body = str(app.screen.query_one(".modal-body", Static).content)
            assert body == (
                "Remove account 'personal' (personal@example.com)?\n\n"
                "Its stored login directory is deleted."
            )
            assert "unmanaged" not in body

    async def test_confirm_remove_of_a_ghost_has_no_extras(self, tmp_path: Path) -> None:
        # dispatch feeds a snapshot row, but the method itself must not
        # crash on a name the snapshot doesn't know
        app, _api, _store, _clock = wired_app(tmp_path)
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            app.actions.confirm_remove("ghost")
            await pilot.pause()
            body = str(app.screen.query_one(".modal-body", Static).content)
            assert body == "Remove account 'ghost'?\n\nIts stored login directory is deleted."


class TestWorkerFailure:
    async def test_a_failed_refresh_clears_the_lane_and_warns_once(self, tmp_path: Path) -> None:
        notes: list[tuple[object, dict[str, object]]] = []
        app, _api, _store, _clock = wired_app(tmp_path, fetch_usage=_RaisingFetchUsage())
        app.notify = lambda message, **kw: notes.append((message, kw))
        async with app.run_test() as pilot:
            await settle_workers(pilot)
            assert app.snapshot is None
            assert not list(app.workers)
            assert "refreshing" not in app.refresh_status
            assert notes == [("Refresh failed: boom", {"severity": "warning", "timeout": 6})]
            # a repeat of the same failure does not notify again
            app.request_refresh()
            await settle_workers(pilot)
            assert not list(app.workers)
            assert len(notes) == 1


class TestUpdateNotice:
    """The mount-time release check — one cached probe, a toast on a hit."""

    async def test_a_newer_release_toasts_on_mount(self, tmp_path: Path) -> None:
        # arrange — the feed reports a newer release than the running one
        notes: list[tuple[object, dict[str, object]]] = []
        app, _api, _store, _clock = wired_app(
            tmp_path, check_update=make_check_update(latest="9.9.9")
        )
        app.notify = lambda message, **kw: notes.append((message, kw))

        # act — mount runs the probe off the UI loop
        async with app.run_test(size=(120, 24)) as pilot:
            await settle_workers(pilot)

        # assert — the shared notice wording, as an informational toast
        assert notes == [
            (
                "cam 9.9.9 is available (you have 1.0.0) — run `cam upgrade`",
                {"severity": "information", "timeout": 8},
            )
        ]

    async def test_no_offer_stays_silent(self, tmp_path: Path) -> None:
        # arrange — feed at parity with the running version
        notes: list[tuple[object, dict[str, object]]] = []
        app, _api, _store, _clock = wired_app(tmp_path, check_update=make_check_update(latest=None))
        app.notify = lambda message, **kw: notes.append((message, kw))

        # act
        async with app.run_test() as pilot:
            await settle_workers(pilot)

        # assert
        assert notes == []

    async def test_updates_mode_off_stays_silent(self, tmp_path: Path) -> None:
        # arrange — a newer release exists but the mode silences the check
        notes: list[tuple[object, dict[str, object]]] = []
        app, _api, _store, _clock = wired_app(
            tmp_path, check_update=make_check_update(latest="9.9.9", mode="off")
        )
        app.notify = lambda message, **kw: notes.append((message, kw))

        # act
        async with app.run_test() as pilot:
            await settle_workers(pilot)

        # assert
        assert notes == []

    async def test_the_env_kill_switch_stays_silent(self, tmp_path: Path) -> None:
        # arrange — the env flag wins over the notify mode
        notes: list[tuple[object, dict[str, object]]] = []
        app, _api, _store, _clock = wired_app(
            tmp_path,
            check_update=make_check_update(latest="9.9.9", env={"CAM_DISABLE_UPDATE_CHECK": "1"}),
        )
        app.notify = lambda message, **kw: notes.append((message, kw))

        # act
        async with app.run_test() as pilot:
            await settle_workers(pilot)

        # assert
        assert notes == []
