"""``cam auto --once`` — the one-shot tick through the dispatch layer.

User-facing output is pinned exactly — the printed line *is* the interface
(docs/architecture.md §10), so a drift in wording is a regression, not cosmetic.
"""

import json
import signal
from dataclasses import replace
from pathlib import Path

import pytest
from support.cli_rigs import STAMP as _STAMP
from support.cli_rigs import auto_credentials as _auto_credentials
from support.cli_rigs import auto_rig as _auto_rig
from support.cli_rigs import dead_lineage_rig as _dead_lineage_rig
from support.cli_rigs import run_cli as _run
from support.cli_rigs import snap_used as _snap_used
from support.in_memory_auto_state import InMemoryAutoState
from support.in_memory_settings import InMemorySettings
from support.in_memory_usage_cache import InMemoryUsageCache
from support.use_cases import make_use_cases

from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.auto.domain.auto_state import AutoState
from claude_acc_manager.settings.domain.settings_spec import setting_spec
from claude_acc_manager.usage.application.ports import AnthropicApiError
from claude_acc_manager.usage.domain.usage_cache_entry import EMPTY_USAGE_CACHE_ENTRY

_use_cases = make_use_cases


class TestAutoOnce:
    """``cam auto --once`` — one tick over the real use cases, fakes at the ports."""

    def test_once_below_threshold_is_no_action(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(50.0), "at-y": _snap_used(20.0)},
            credentials=_auto_credentials("x", "y"),
        )

        # act
        code = _run(["auto", "--once"], use_cases)

        # assert
        assert code == 2
        assert capsys.readouterr().out == (
            f"{_STAMP}  x: 50% used (switch at 90%) | others: y: 5h 20%\n"
            f"{_STAMP}  no switch: below-threshold (50% < 90%)\n"
        )

    def test_once_switches_onto_a_qualifying_candidate(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — x over threshold; y credentialed and roomy
        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(95.0), "at-y": _snap_used(20.0)},
            credentials=_auto_credentials("x", "y"),
        )

        # act
        code = _run(["auto", "--once"], use_cases)

        # assert
        assert code == 0
        assert capsys.readouterr().out == (
            f"{_STAMP}  x: 95% used (switch at 90%) | others: y: 5h 20%\n"
            f"{_STAMP}  Switched x -> y (proactive)\n"
        )
        slot = use_cases.status
        assert slot.execute() is not None and slot.execute().managed_as == "y"

    def test_once_all_exhausted_is_blocked_exit_3(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(100.0), "at-y": _snap_used(100.0)},
            credentials=_auto_credentials("x", "y"),
        )

        # act
        code = _run(["auto", "--once"], use_cases)

        # assert
        assert code == 3
        assert capsys.readouterr().out == (
            f"{_STAMP}  x: 100% used (switch at 90%) | others: y: 5h 100%\n"
            f"{_STAMP}  all accounts exhausted; no reset time known\n"
        )

    def test_once_exhausted_line_names_the_earliest_reset(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — y reports a reset an hour past the pinned clock
        use_cases = _auto_rig(
            tmp_path,
            snaps={
                "at-x": _snap_used(100.0, reset_s=1_007_200.0),
                "at-y": _snap_used(100.0, reset_s=1_003_600.0),
            },
            credentials=_auto_credentials("x", "y"),
        )

        # act
        code = _run(["auto", "--once"], use_cases)

        # assert
        assert code == 3
        assert "all accounts exhausted; earliest reset 1970-01-12T14:46:40Z\n" in (
            capsys.readouterr().out
        )

    def test_once_dry_run_decides_without_mutating(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        auto_state = InMemoryAutoState()
        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(95.0), "at-y": _snap_used(20.0)},
            credentials=_auto_credentials("x", "y"),
            auto_state=auto_state,
        )
        slot_before = use_cases.status.execute()

        # act
        code = _run(["auto", "--once", "--dry-run"], use_cases)

        # assert — would-be switch rendered, nothing moved, nothing recorded
        assert code == 0
        assert "[dry-run] would switch x -> y (proactive)\n" in capsys.readouterr().out
        assert use_cases.status.execute() == slot_before
        assert auto_state.load() == AutoState()
        assert (
            use_cases.account_files.read_credentials(
                use_cases.account_store.account_dir(AccountName("y"))
            )
            is not None
        )

    def test_once_honors_a_persisted_threshold(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — 85% sits under the 90 default but over the stored 80
        settings = InMemorySettings(tmp_path)
        settings.set_value(setting_spec("autoswitch.threshold"), 80.0)
        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(85.0), "at-y": _snap_used(20.0)},
            credentials=_auto_credentials("x", "y"),
            settings=settings,
        )

        # act
        code = _run(["auto", "--once"], use_cases)

        # assert
        assert code == 0
        assert "switch at 80%" in capsys.readouterr().out

    def test_once_threshold_flag_overrides_settings(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — the flag, not the file, binds this tick
        settings = InMemorySettings(tmp_path)
        settings.set_value(setting_spec("autoswitch.threshold"), 95.0)
        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(85.0), "at-y": _snap_used(20.0)},
            credentials=_auto_credentials("x", "y"),
            settings=settings,
        )

        # act
        code = _run(["auto", "--once", "--threshold", "80"], use_cases)

        # assert
        assert code == 0
        assert "switch at 80%" in capsys.readouterr().out

    def test_once_cooldown_flag_releases_the_hold(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — a switch 100s ago; the default 300s cooldown holds it
        state = AutoState(last_switch_at_s=999_900.0, last_switch_from="x", last_switch_to="y")
        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(95.0), "at-y": _snap_used(20.0)},
            credentials=_auto_credentials("x", "y"),
            auto_state=InMemoryAutoState(state),
        )

        # act / assert — default cooldown blocks; --cooldown 1 releases
        assert _run(["auto", "--once"], use_cases) == 2
        assert f"{_STAMP}  no switch: cooldown\n" in capsys.readouterr().out
        assert _run(["auto", "--once", "--cooldown", "1"], use_cases) == 0

    def test_once_flag_out_of_range_fails_loudly(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # act
        code = _run(
            ["auto", "--once", "--threshold", "999"],
            _auto_rig(tmp_path, snaps={}),
        )

        # assert — the strict overlay speaks, not a silent clamp
        assert code == 1
        assert "between 50 and 99.9" in capsys.readouterr().err

    def test_once_logged_out_is_no_action(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # act — the default rig has a parked account but no live slot
        code = _run(["auto", "--once"], _use_cases(tmp_path))

        # assert
        assert code == 2
        assert capsys.readouterr().out == (
            f"{_STAMP}  poll: no active account\n"
            f"{_STAMP}  no switch: no-active-account (log in and run 'cam add' first)\n"
        )

    def test_once_a_port_failure_is_error_exit_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — the state port dies inside the tick's never-raises net
        class _RaisingAutoState(InMemoryAutoState):
            def load(self) -> AutoState:
                raise RuntimeError("boom")

        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(50.0)},
            credentials=_auto_credentials("x"),
            auto_state=_RaisingAutoState(),
        )

        # act
        code = _run(["auto", "--once"], use_cases)

        # assert
        assert code == 1
        assert f"{_STAMP}  error: RuntimeError: boom (will retry)\n" in (capsys.readouterr().out)

    def test_once_does_not_install_a_signal_handler(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # arrange
        installed: dict[int, object] = {}
        monkeypatch.setattr(
            signal, "signal", lambda sig, handler: installed.setdefault(sig, handler)
        )
        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(50.0)},
            credentials=_auto_credentials("x"),
        )

        # act
        code = _run(["auto", "--once"], use_cases)

        # assert — signal wiring is loop-mode only
        assert code == 2
        assert installed == {}

    def test_once_quarantines_a_dead_lineage(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — y's parked refresh grant is provably dead
        use_cases = _dead_lineage_rig(tmp_path)

        # act
        code = _run(["auto", "--once"], use_cases)

        # assert — the lineage is tombstoned and the tick reports BLOCKED
        assert code == 3
        assert capsys.readouterr().out == (
            f"{_STAMP}  x: 95% used (switch at 90%) | others: y: 5h 20%\n"
            f"{_STAMP}  y quarantined: invalid_grant. "
            "Log in with it and run 'cam add y' to recover.\n"
            f"{_STAMP}  no switch: no-viable-target\n"
        )
        (entry,) = use_cases.account_store.quarantined()
        assert entry.name == "y"
        assert entry.reason == "permanent_auth_error"

    def test_once_reports_fetch_errors_in_the_census(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — every poll fails; headroom is unmeasurable
        use_cases = _auto_rig(
            tmp_path,
            snaps={
                "at-x": AnthropicApiError(429, "rate_limit_error"),
                "at-y": AnthropicApiError(500, "api_error"),
            },
            credentials=_auto_credentials("x", "y"),
        )

        # act
        code = _run(["auto", "--once"], use_cases)

        # assert — the census explains itself; unknown active usage can't act
        assert code == 2
        assert capsys.readouterr().out == (
            f"{_STAMP}  x: usage unknown (http-429) (switch at 90%) | others: y: ? (http-500)\n"
            f"{_STAMP}  no switch: active-usage-unknown\n"
        )

        # act — JSONL names the same causes on a fresh rig (backoff arms after
        # the first tick and would change the wording on a rerun)
        json_rig = _auto_rig(
            tmp_path,
            snaps={
                "at-x": AnthropicApiError(429, "rate_limit_error"),
                "at-y": AnthropicApiError(500, "api_error"),
            },
            credentials=_auto_credentials("x", "y"),
        )
        assert _run(["auto", "--once", "--json"], json_rig) == 2

        # assert
        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert lines[0]["fetchErrors"] == {"x": "http-429", "y": "http-500"}

    def test_once_renders_a_never_polled_parked_account(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — y's row is not due (a far deadline would oversleep and
        # re-enter the plan) and holds nothing yet: a bare "?"
        cache = InMemoryUsageCache()
        cache.save(
            "y",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                fetched_at_s=999_000.0,
                next_poll_at_s=1_000_300.0,
            ),
        )
        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(50.0)},
            credentials=_auto_credentials("x"),
            cache=cache,
        )

        # act
        code = _run(["auto", "--once"], use_cases)

        # assert
        assert code == 2
        assert capsys.readouterr().out == (
            f"{_STAMP}  x: 50% used (switch at 90%) | others: y: ?\n"
            f"{_STAMP}  no switch: below-threshold (50% < 90%)\n"
        )

    def test_once_renders_unknown_active_usage_without_a_cause(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — x's row was fetched recently and its plan is not due, so
        # the tick skips it entirely; with no candidates there is nothing to
        # escalate either: bare "usage unknown", no recorded cause
        cache = InMemoryUsageCache()
        cache.save(
            "x",
            replace(
                EMPTY_USAGE_CACHE_ENTRY,
                fetched_at_s=1_000_000.0,
                next_poll_at_s=1_000_300.0,
            ),
        )
        use_cases = _auto_rig(
            tmp_path,
            snaps={},
            credentials=_auto_credentials("x"),
            cache=cache,
            parked=(),
        )

        # act
        code = _run(["auto", "--once"], use_cases)

        # assert
        assert code == 2
        assert capsys.readouterr().out == (
            f"{_STAMP}  x: usage unknown (switch at 90%)\n"
            f"{_STAMP}  no switch: active-usage-unknown\n"
        )

    def test_once_joins_multi_window_and_multi_account_rows(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — two parked accounts; the poll picks one, so z stays "?"
        use_cases = _auto_rig(
            tmp_path,
            snaps={"at-x": _snap_used(50.0), "at-y": _snap_used(50.0, seven_pct=40.0)},
            credentials=_auto_credentials("x", "y"),
            parked=("y", "z"),
        )

        # act
        code = _run(["auto", "--once"], use_cases)

        # assert — the census joins windows with " · " and accounts with ", "
        assert code == 2
        assert capsys.readouterr().out == (
            f"{_STAMP}  x: 50% used (switch at 90%) | others: y: 5h 50% · 7d 40%, z: ?\n"
            f"{_STAMP}  no switch: below-threshold (50% < 90%)\n"
        )
