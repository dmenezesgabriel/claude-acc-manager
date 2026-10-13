"""``cam``-dispatch rigs shared by the ``test_cli_*`` command suites.

One home for the helpers the per-command-area files share: the dispatch
entry points (``run_cli``/``run_cli_tty``), the store/credential seeders
(``park_account``/``config_for``/``cache_usage``), and the per-command
``UseCases`` builders (``auto_rig``/``dead_lineage_rig``/``upgrade_rig``/
``offering_use_cases``). Everything here wires named fakes — hermetic by
construction, like ``support/use_cases.py``.
"""

import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from rich.console import Console

from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.auto.application.use_cases.freshen_target import FreshenTarget
from claude_acc_manager.cli import ProcessContext, UseCases, run
from claude_acc_manager.shared.claude_contract import contract_for_version
from claude_acc_manager.update.application.use_cases.self_upgrade import SelfUpgrade
from claude_acc_manager.update.domain.services.install_method import InstallMethod
from claude_acc_manager.usage.application.ports import AnthropicApiError, RefreshedTokens
from claude_acc_manager.usage.domain.oauth_credential import StoredOAuthCredential
from claude_acc_manager.usage.domain.usage_cache_entry import EMPTY_USAGE_CACHE_ENTRY
from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot, UsageWindow
from support.controllable_clock import ControllableClock
from support.fake_account_dir import FakeAccountDir
from support.fake_active_slot import FakeActiveSlot
from support.fake_claude_contract import FakeClaudeContractProbe
from support.fake_credential_store import FakeCredentialStore
from support.fake_token_refresher import FakeTokenRefresher
from support.fake_upgrade_runner import FakeUpgradeRunner
from support.fake_usage_api import FakeUsageApi
from support.in_memory_account_store import InMemoryAccountStore
from support.in_memory_auto_state import InMemoryAutoState
from support.in_memory_settings import InMemorySettings
from support.in_memory_usage_cache import InMemoryUsageCache
from support.recording_stream import RecordingStream
from support.use_cases import (
    credentials_for,
    make_account,
    make_check_update,
    make_fetch_usage,
    make_use_cases,
)


def run_cli(argv: list[str], use_cases: UseCases) -> int:
    """Dispatch under a non-root, non-container process context."""
    return run(argv, use_cases, process=ProcessContext(euid=1000, in_container=False))


def run_cli_tty(argv: list[str], use_cases: UseCases) -> tuple[int, str, str]:
    """Dispatch under forced-color consoles; return (code, stdout, stderr).

    The style pins live here: capsys's non-tty capture proves wording, and
    these streams prove the ANSI that wraps it on a color terminal.
    """
    out_stream = RecordingStream()
    err_stream = RecordingStream()
    code = run(
        argv,
        use_cases,
        process=ProcessContext(euid=1000, in_container=False),
        console=Console(file=out_stream, force_terminal=True, width=200),
        err_console=Console(file=err_stream, force_terminal=True, width=200),
    )
    return code, out_stream.getvalue(), err_stream.getvalue()


def config_for(account_uuid: str) -> dict[str, object]:
    """A ``.claude.json``-shaped config whose ``oauthAccount`` names the uuid."""
    return {"oauthAccount": {"emailAddress": "user@example.com", "accountUuid": account_uuid}}


def park_account(store: InMemoryAccountStore, reader: FakeAccountDir, name: str) -> None:
    """Register *name* with its credential parked in its account dir."""
    store.upsert(make_account(name, account_uuid=f"acc-{name}"))
    reader.put(
        store.account_dir(AccountName(name)),
        credentials=credentials_for(name),
        config=config_for(f"acc-{name}"),
    )


def cache_usage(cache: InMemoryUsageCache, name: str, pct: float) -> None:
    """Seed one account's cached usage snapshot (pct = percent used)."""
    snapshot = UsageSnapshot(
        five_hour=UsageWindow(pct=pct, resets_at=None), seven_day=None, scoped=()
    )
    cache.save(name, replace(EMPTY_USAGE_CACHE_ENTRY, last_good=snapshot))


def snap_used(
    pct: float, reset_s: float | None = None, seven_pct: float | None = None
) -> UsageSnapshot:
    """A one/two-window snapshot; *reset_s* is an epoch, rendered the API's ISO-Z."""
    return UsageSnapshot(
        five_hour=UsageWindow(
            pct=pct,
            resets_at=(
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(reset_s)) if reset_s else None
            ),
        ),
        seven_day=UsageWindow(pct=seven_pct, resets_at=None) if seven_pct is not None else None,
        scoped=(),
    )


def auto_credentials(*names: str) -> FakeCredentialStore:
    """Parked credentials whose access tokens are ``at-<name>``."""
    return FakeCredentialStore(
        credentials={
            name: StoredOAuthCredential(
                access_token=f"at-{name}",
                refresh_token=f"rt-{name}",
                expires_at_ms=1e13,
            )
            for name in names
        }
    )


def auto_rig(
    tmp_path: Path,
    *,
    snaps: dict[str, UsageSnapshot | Exception],
    credentials: FakeCredentialStore | None = None,
    settings: InMemorySettings | None = None,
    auto_state: InMemoryAutoState | None = None,
    freshen_target: FreshenTarget | None = None,
    cache: InMemoryUsageCache | None = None,
    refresher: FakeTokenRefresher | None = None,
    parked: tuple[str, ...] = ("y",),
    clock_s: float = 1_000_000.0,
) -> UseCases:
    """x live plus *parked* accounts — wired for ``cam auto`` dispatches.

    Fresh rows are all due, so the tick fetches everyone: ``snaps`` keys
    are access tokens, and the matching ``at-<name>`` credentials make each
    account read its own scripted value.
    """
    store = InMemoryAccountStore(tmp_path)
    reader = FakeAccountDir()
    park_account(store, reader, "x")
    for name in parked:
        park_account(store, reader, name)
    reader.delete_credentials(store.account_dir(AccountName("x")))
    store.set_active(AccountName("x"))
    slot = FakeActiveSlot(credentials=credentials_for("x"), config=config_for("acc-x"))
    resolved_credentials = credentials or FakeCredentialStore()
    resolved_cache = cache or InMemoryUsageCache()
    usage_clock = ControllableClock(now_epoch_s=clock_s)
    fetch = make_fetch_usage(
        usage_api=FakeUsageApi(by_token=snaps),
        refresher=refresher,
        credentials=resolved_credentials,
        usage_cache=resolved_cache,
        usage_clock=usage_clock,
    )
    return make_use_cases(
        tmp_path,
        store=store,
        reader=reader,
        slot=slot,
        fetch_usage=fetch,
        usage_cache=resolved_cache,
        usage_clock=usage_clock,
        credentials=resolved_credentials,
        settings=settings,
        auto_state=auto_state,
        freshen_target=freshen_target,
    )


def dead_lineage_rig(tmp_path: Path) -> UseCases:
    """x live at 95%; y parked with an expired grant the fresher rejects.

    x inside the escalation band force-refreshes y: the poll's own grant
    succeeds but writes a zero-lifetime rotation, so y is still expired
    when *freshen* runs and *its* grant returns ``invalid_grant`` — dead.
    """
    credentials = FakeCredentialStore(
        credentials={
            "x": StoredOAuthCredential("at-x", "rt-x", 1e13),
            "y": StoredOAuthCredential("at-y", "rt-y", 0.0),
        }
    )
    return auto_rig(
        tmp_path,
        snaps={"at-x": snap_used(95.0), "at-y2": snap_used(20.0)},
        credentials=credentials,
        refresher=FakeTokenRefresher(refreshed=RefreshedTokens("at-y2", "rt-y2", expires_in_s=0.0)),
        freshen_target=FreshenTarget(
            FakeTokenRefresher(error=AnthropicApiError(400, "invalid_grant")),
            credentials,
            ControllableClock(now_epoch_s=1_000_000.0),
            FakeClaudeContractProbe(contract_for_version((2, 1, 288))),
        ),
    )


def until(predicate: Callable[[], bool], timeout_s: float = 5.0) -> bool:
    """Poll *predicate* to true or *timeout_s* — for loop tests asserting on async state."""
    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    return predicate()


def upgrade_rig(
    tmp_path: Path, method: InstallMethod, runner: FakeUpgradeRunner | None = None
) -> tuple[UseCases, FakeUpgradeRunner]:
    """UseCases whose SelfUpgrade sits on *method* over a recording runner."""
    runner = runner if runner is not None else FakeUpgradeRunner()
    use_cases = make_use_cases(tmp_path, self_upgrade=SelfUpgrade(runner, method=method))
    return use_cases, runner


def offering_use_cases(tmp_path: Path, **kwargs: object) -> UseCases:
    """UseCases whose check reports a newer release, plus the caller's seams."""
    return make_use_cases(tmp_path, check_update=make_check_update(latest="9.9.9"), **kwargs)
