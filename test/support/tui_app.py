"""Shared Pilot harness for CamApp tests.

``wired_app`` wires a CamApp over the same named fakes the CLI tests use
(accounts on disk, live slot, in-memory usage cache, controllable clock);
``settle_workers`` drains refresh workers and their queued UI updates so
assertions see a fully-applied snapshot.
"""

from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path

from textual.worker import WorkerFailed

from claude_acc_manager.accounts.application.use_cases.collect_accounts_view import (
    AccountsView,
    CollectAccountsView,
)
from claude_acc_manager.accounts.application.use_cases.switch_account import SwitchAccount
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.tui.app import CamApp
from claude_acc_manager.usage.application.use_cases.fetch_account_usage import (
    FetchAccountUsage,
)
from support.controllable_clock import ControllableClock
from support.fake_account_dir import FakeAccountDir
from support.fake_active_slot import FakeActiveSlot
from support.fake_credential_store import FakeCredentialStore
from support.fake_token_refresher import FakeTokenRefresher
from support.fake_usage_api import FakeUsageApi
from support.in_memory_account_store import InMemoryAccountStore
from support.in_memory_usage_cache import InMemoryUsageCache
from support.use_cases import (
    SEEDED_CONFIG,
    SEEDED_SNAPSHOT,
    credentials_for,
    make_account,
    make_fetch_usage,
    make_use_cases,
    stored_credential,
)


def wired_app(
    tmp_path: Path,
    names: tuple[str, ...] = ("work", "personal"),
    *,
    start: str = "dashboard",
    active_name: str | None = None,
    usage_api: FakeUsageApi | None = None,
    refresher: FakeTokenRefresher | None = None,
    fetch_usage: FetchAccountUsage | None = None,
    collect_view: CollectAccountsView | None = None,
    collect_gate: threading.Event | None = None,
    switch: SwitchAccount | None = None,
    expired_credentials: bool = False,
    usage_cache: InMemoryUsageCache | None = None,
) -> tuple[CamApp, FakeUsageApi, InMemoryAccountStore, ControllableClock]:
    """A CamApp over shared fakes; returns the seams tests assert against."""
    store = InMemoryAccountStore(tmp_path)
    reader = FakeAccountDir()
    for name in names:
        store.upsert(make_account(name, account_uuid=f"uuid-{name}"))
        reader.put(
            store.account_dir(AccountName(name)),
            credentials=credentials_for(name),
            config=SEEDED_CONFIG,
        )
    slot_config = (
        {
            "oauthAccount": {
                "emailAddress": f"{active_name}@test.invalid",
                "accountUuid": f"uuid-{active_name}",
            }
        }
        if active_name
        else None
    )
    if active_name:
        # The real live state: registry pointer set, credentials in the slot,
        # and the active account's parked dir holding config only.
        store.set_active(AccountName(active_name))
        reader.delete_credentials(store.account_dir(AccountName(active_name)))
    cache = usage_cache or InMemoryUsageCache()
    clock = ControllableClock(now_epoch_s=1_000_000.0)
    api = usage_api or FakeUsageApi(snapshot=SEEDED_SNAPSHOT)
    fetcher = fetch_usage or make_fetch_usage(
        usage_api=api,
        refresher=refresher,
        credentials=FakeCredentialStore(
            credentials={
                name: stored_credential(expires_at_ms=0.0 if expired_credentials else None)
                for name in names
            }
        ),
        usage_cache=cache,
        usage_clock=clock,
    )
    use_cases = make_use_cases(
        tmp_path,
        store=store,
        reader=reader,
        slot=FakeActiveSlot(
            config=slot_config,
            credentials=credentials_for(active_name) if active_name else None,
        ),
        fetch_usage=fetcher,
        collect_view=collect_view,
        usage_cache=cache,
        usage_clock=clock,
    )
    if switch is not None:
        use_cases = replace(use_cases, switch=switch)
    if collect_gate is not None:
        use_cases = replace(
            use_cases, collect_view=_GatedCollect(use_cases.collect_view, collect_gate)
        )
    app = CamApp(use_cases, start=start)
    # Tests drive refresh explicitly via request_refresh(); the interval timer
    # is parked far away so a slow assertion cannot interleave a second poll.
    app.POLL_INTERVAL_S = 3600.0
    return app, api, store, clock


class _GatedCollect:
    """Delegate that parks ``execute`` until the test opens the gate.

    Gives a test a deterministic window where ``app.snapshot`` is still
    ``None`` — without it the fake-backed collect finishes inside the first
    event-loop turn and the pre-snapshot path is a race.
    """

    def __init__(self, inner: CollectAccountsView, gate: threading.Event) -> None:
        self._inner = inner
        self._gate = gate

    def execute(self) -> AccountsView:
        self._gate.wait(timeout=10)
        return self._inner.execute()


async def settle_workers(pilot) -> None:
    """Let refresh workers finish and their queued UI updates apply.

    ``wait_for_complete`` re-raises worker errors; the app already surfaces
    them through ``on_worker_state_changed``, so the raise is drained here.
    """
    app = pilot.app
    pending = list(app.workers)
    if pending:
        try:
            await app.workers.wait_for_complete(pending)
        except WorkerFailed:
            pass
    await pilot.pause()
    await pilot.pause()
