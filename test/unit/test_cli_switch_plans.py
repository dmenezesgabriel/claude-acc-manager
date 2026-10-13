"""``cam switch`` — strategy selection, stays, and dry-run plans.

User-facing output is pinned exactly — the printed line *is* the interface
(docs/architecture.md §10), so a drift in wording is a regression, not cosmetic.
"""

from pathlib import Path

import pytest
from support.cli_rigs import cache_usage as _cache_usage
from support.cli_rigs import config_for as _config_for
from support.cli_rigs import park_account as _park
from support.cli_rigs import run_cli as _run
from support.fake_account_dir import FakeAccountDir
from support.fake_active_slot import FakeActiveSlot
from support.in_memory_account_store import InMemoryAccountStore
from support.in_memory_usage_cache import InMemoryUsageCache
from support.use_cases import credentials_for, make_use_cases

from claude_acc_manager.accounts.domain.value_objects import AccountName

_use_cases = make_use_cases
_creds_for = credentials_for


class TestSwitchCommand:
    def test_best_strategy_picks_the_roomiest_measured_candidate(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — x live at 80% used; y at 90%, z at 30%
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        _park(store, reader, "z")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))
        cache = InMemoryUsageCache()
        _cache_usage(cache, "x", 80.0)
        _cache_usage(cache, "y", 90.0)
        _cache_usage(cache, "z", 30.0)

        # act
        code = _run(
            ["switch", "--strategy", "best"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot, usage_cache=cache),
        )

        # assert
        assert code == 0
        assert capsys.readouterr().out == "switched to 'z' (was 'x')\n"

    def test_next_available_skips_an_exhausted_candidate(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — y is at its limit (0 headroom); z still has room
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        _park(store, reader, "z")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))
        cache = InMemoryUsageCache()
        _cache_usage(cache, "y", 100.0)
        _cache_usage(cache, "z", 30.0)

        # act
        code = _run(
            ["switch", "--strategy", "next-available"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot, usage_cache=cache),
        )

        # assert
        assert code == 0
        assert capsys.readouterr().out == ("switched to 'z' (was 'x')\nskipped 'y': at-limit\n")

    def test_dry_run_reports_the_plan_without_moving_anything(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))

        # act
        code = _run(
            ["switch", "y", "--dry-run"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot),
        )

        # assert — nothing moved
        assert code == 0
        assert capsys.readouterr().out == "dry run: switched to 'y' (was 'x')\n"
        assert slot.read_credentials() == _creds_for("x")
        y_dir = store.account_dir(AccountName("y"))
        assert reader.read_credentials(y_dir) == _creds_for("y")
        active = store.active()
        assert active is not None and active.name.value == "x"

    def test_candidates_exhausted_reports_the_stay(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — every candidate measured at its limit
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))
        cache = InMemoryUsageCache()
        _cache_usage(cache, "y", 100.0)

        # act
        code = _run(
            ["switch", "--strategy", "next-available"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot, usage_cache=cache),
        )

        # assert
        assert code == 0
        assert capsys.readouterr().out == (
            "every candidate is at its limit\nskipped 'y': at-limit\n"
        )

    def test_no_valid_target_reports_the_stay(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — x live, the only other account disabled
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        store.set_enabled(AccountName("y"), False)
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))

        # act
        code = _run(["switch"], _use_cases(tmp_path, store=store, reader=reader, slot=slot))

        # assert
        assert code == 0
        assert capsys.readouterr().out == ("no valid switch target\nskipped 'y': disabled\n")

    def test_best_without_a_current_measurement_reports_usage_unavailable(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — the live account was never measured, so no candidate can
        # provably beat it
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))
        cache = InMemoryUsageCache()
        _cache_usage(cache, "y", 10.0)

        # act
        code = _run(
            ["switch", "--strategy", "best"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot, usage_cache=cache),
        )

        # assert
        assert code == 0
        assert capsys.readouterr().out == "usage unknown — cannot rank candidates\n"

    def test_best_when_the_live_account_already_leads_reports_already_best(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — x live at 10% used, y at 90%
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))
        cache = InMemoryUsageCache()
        _cache_usage(cache, "x", 10.0)
        _cache_usage(cache, "y", 90.0)

        # act
        code = _run(
            ["switch", "--strategy", "best"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot, usage_cache=cache),
        )

        # assert
        assert code == 0
        assert capsys.readouterr().out == ("the active account already has the most headroom\n")

    def test_dry_run_reports_the_unmanaged_preservation_it_would_make(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — foreign live login; --dry-run must preview the preserve
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        slot = FakeActiveSlot(credentials=_creds_for("foreign"), config=_config_for("acc-foreign"))

        # act
        code = _run(
            ["switch", "x", "--dry-run"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot),
        )

        # assert — no real path exists yet, so the note names the stash dir
        assert code == 0
        assert capsys.readouterr().out == (
            "dry run: switched to 'x' (was an unmanaged login)\n"
            "dry run: the previous unmanaged login was preserved under unclaimed/\n"
        )
