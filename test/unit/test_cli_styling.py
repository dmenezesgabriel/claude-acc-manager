"""ANSI chrome over the pinned wording — only under a forced-TTY console.

Styling is a presentation-layer concern: these tests run ``run()`` with a
``force_terminal`` console over a ``RecordingStream`` and pin the escape
sequences, not just the text.
"""

from dataclasses import replace
from pathlib import Path

from rich.console import Console
from support.cli_rigs import cache_usage as _cache_usage
from support.cli_rigs import config_for as _config_for
from support.cli_rigs import park_account as _park
from support.cli_rigs import run_cli_tty as _run_tty
from support.controllable_clock import ControllableClock
from support.fake_account_dir import FakeAccountDir
from support.fake_active_slot import FakeActiveSlot
from support.fake_claude_contract import FakeClaudeContractProbe
from support.fake_credential_store import FakeCredentialStore
from support.fake_token_refresher import FakeTokenRefresher
from support.fake_usage_api import FakeUsageApi
from support.in_memory_account_store import InMemoryAccountStore
from support.in_memory_settings import emails_visible_settings
from support.in_memory_usage_cache import InMemoryUsageCache
from support.recording_stream import RecordingStream
from support.use_cases import SEEDED_SNAPSHOT as _USAGE_SNAPSHOT
from support.use_cases import credentials_for as _creds_for
from support.use_cases import make_account as _account
from support.use_cases import make_fetch_usage as _fetch_usage
from support.use_cases import make_use_cases as _use_cases
from support.use_cases import stored_credential as _stored_credential

from claude_acc_manager.accounts.domain.entities import QuarantineEntry
from claude_acc_manager.accounts.domain.value_objects import AccountName
from claude_acc_manager.cli import ProcessContext, run
from claude_acc_manager.shared.claude_contract import contract_for_version
from claude_acc_manager.usage.application.ports import AnthropicApiError
from claude_acc_manager.usage.application.use_cases.fetch_account_usage import (
    FetchAccountUsage,
)
from claude_acc_manager.usage.domain.usage_cache_entry import EMPTY_USAGE_CACHE_ENTRY
from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot, UsageWindow


class TestHumanStyling:
    """ANSI chrome over the pinned wording — only under a color console."""

    def test_the_active_list_marker_is_accented(self, tmp_path: Path):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        store.set_active(AccountName("work"))

        # act
        code, out, _ = _run_tty(
            ["list"],
            _use_cases(tmp_path, store=store, settings=emails_visible_settings(tmp_path)),
        )

        # assert — bold-cyan `*`; the literal tab survives inside the row
        assert code == 0
        assert "\x1b[1;36m*\x1b[0m" in out
        assert "\twork@example.com" in out

    def test_disabled_and_quarantined_flags_carry_severity(self, tmp_path: Path):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        store.upsert(_account("personal"))
        store.set_enabled(AccountName("personal"), False)
        store.set_quarantined(
            QuarantineEntry("work", "permanent_auth_error", "2026-10-01T00:00:00Z", "sha256:x")
        )

        # act
        code, out, _ = _run_tty(["list"], _use_cases(tmp_path, store=store))

        # assert — dim [disabled], yellow [quarantined]
        assert code == 0
        assert "\x1b[2m [disabled]\x1b[0m" in out
        assert "\x1b[33m [quarantined]\x1b[0m" in out

    def test_usage_pcts_ride_the_severity_ramp(self, tmp_path: Path):
        # arrange — five_hour at 95% sits over the CRIT edge
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        snapshot = UsageSnapshot(
            five_hour=UsageWindow(pct=95.0, resets_at=None),
            seven_day=UsageWindow(pct=27.0, resets_at=None),
            scoped=(),
        )
        credentials = FakeCredentialStore(credentials={"work": _stored_credential()})
        fetch_usage = _fetch_usage(
            usage_api=FakeUsageApi(snapshot=snapshot), credentials=credentials
        )

        # act
        code, out, _ = _run_tty(
            ["usage", "work"], _use_cases(tmp_path, store=store, fetch_usage=fetch_usage)
        )

        # assert — 95% red, 27% green; the labels stay plain
        assert code == 0
        assert "\x1b[31m95%\x1b[0m" in out
        assert "\x1b[32m27%\x1b[0m" in out

    def test_an_error_line_gets_a_red_prefix_on_stderr(self, tmp_path: Path):
        # act — an unknown account raises through the handled-error path
        code, _, err = _run_tty(["usage", "ghost"], _use_cases(tmp_path))

        # assert — the `error:` prefix is red, the message untouched
        assert code == 1
        assert err == "\x1b[31merror:\x1b[0m no such account: 'ghost'\n"

    def test_a_confirmation_is_bold(self, tmp_path: Path):
        # act
        code, out, _ = _run_tty(["add", "work"], _use_cases(tmp_path))

        # assert
        assert code == 0
        assert "\x1b[1madded account 'work'\x1b[0m" in out

    def test_a_real_switch_confirmation_is_bold(self, tmp_path: Path):
        # arrange — x live, y parked (the standard switch rig)
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        _park(store, reader, "y")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        slot = FakeActiveSlot(credentials=_creds_for("x"), config=_config_for("acc-x"))

        # act
        code, out, _ = _run_tty(
            ["switch", "y"], _use_cases(tmp_path, store=store, reader=reader, slot=slot)
        )

        # assert — the success line is a confirmation: bold
        assert code == 0
        assert "\x1b[1mswitched to 'y' (was 'x')\x1b[0m" in out

    def test_the_error_prefix_stays_red_with_a_piped_stdout(self, tmp_path: Path):
        # arrange — stdout piped (no color), stderr a tty (color): the
        # fragment must follow the *err* console's detection
        err_stream = RecordingStream()

        # act
        code = run(
            ["usage", "ghost"],
            _use_cases(tmp_path),
            process=ProcessContext(euid=1000, in_container=False),
            console=Console(file=RecordingStream()),
            err_console=Console(file=err_stream, force_terminal=True),
        )

        # assert — red survives stdout losing its color
        assert code == 1
        assert err_stream.getvalue() == "\x1b[31merror:\x1b[0m no such account: 'ghost'\n"

    def test_a_remove_confirmation_is_bold(self, tmp_path: Path):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))

        # act
        code, out, _ = _run_tty(["remove", "work"], _use_cases(tmp_path, store=store))

        # assert
        assert code == 0
        assert "\x1b[1mremoved account 'work'\x1b[0m" in out

    def test_a_disable_confirmation_is_bold(self, tmp_path: Path):
        # arrange
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))

        # act
        code, out, _ = _run_tty(["disable", "work"], _use_cases(tmp_path, store=store))

        # assert
        assert code == 0
        assert "\x1b[1mdisabled account 'work'\x1b[0m" in out

    def test_config_set_and_unset_confirmations_are_bold(self, tmp_path: Path):
        # arrange — one instance: unset must see the set
        use_cases = _use_cases(tmp_path)

        # act
        code_set, out_set, _ = _run_tty(["config", "set", "autoswitch.threshold", "80"], use_cases)
        code_unset, out_unset, _ = _run_tty(["config", "unset", "autoswitch.threshold"], use_cases)

        # assert
        assert code_set == 0
        assert "\x1b[1mautoswitch.threshold = 80\x1b[0m" in out_set
        assert code_unset == 0
        assert "\x1b[1mautoswitch.threshold unset (default: 90)\x1b[0m" in out_unset

    def test_usage_unknown_and_the_quarantine_note_carry_severity(self, tmp_path: Path):
        # arrange — the parked account's expired token gets invalid_grant
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        reader = FakeAccountDir()
        parked = {"claudeAiOauth": {"accessToken": "at", "refreshToken": "rt-dead"}}
        reader.put(
            store.account_dir(AccountName("work")),
            credentials=parked,
            config=_config_for("acc-x"),
        )
        credentials = FakeCredentialStore(
            credentials={"work": _stored_credential(expires_at_ms=0.0)}
        )
        fetch_usage = _fetch_usage(
            credentials=credentials,
            refresher=FakeTokenRefresher(error=AnthropicApiError(400, "invalid_grant")),
        )

        # act
        code, out, _ = _run_tty(
            ["usage", "work"], _use_cases(tmp_path, store=store, fetch_usage=fetch_usage)
        )

        # assert — unknown reads dim, the quarantine note yellow
        assert code == 0
        assert "\x1b[2musage unknown: invalid_grant\x1b[0m" in out
        assert (
            "\x1b[33mquarantined 'work': the provider permanently rejected "
            "its refresh token\x1b[0m" in out
        )

    def test_a_stale_note_reads_dim(self, tmp_path: Path):
        # arrange — a frozen last_good served after a 429
        store = InMemoryAccountStore(tmp_path)
        store.upsert(_account("work"))
        cache = InMemoryUsageCache()
        cache.save(
            "work",
            replace(EMPTY_USAGE_CACHE_ENTRY, last_good=_USAGE_SNAPSHOT, fetched_at_s=999_800.0),
        )
        credentials = FakeCredentialStore(credentials={"work": _stored_credential()})
        fetch_usage = FetchAccountUsage(
            FakeUsageApi(error=AnthropicApiError(429, None)),
            FakeTokenRefresher(),
            credentials,
            cache,
            ControllableClock(now_epoch_s=1_000_000.0),
            FakeClaudeContractProbe(contract_for_version((2, 1, 288))),
            threshold=90.0,
        )

        # act
        code, out, _ = _run_tty(
            ["usage", "work"], _use_cases(tmp_path, store=store, fetch_usage=fetch_usage)
        )

        # assert
        assert code == 0
        assert "\x1b[2m(stale: http-429)\x1b[0m" in out

    def test_a_skipped_candidate_reads_dim(self, tmp_path: Path):
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
        code, out, _ = _run_tty(
            ["switch", "--strategy", "next-available"],
            _use_cases(tmp_path, store=store, reader=reader, slot=slot, usage_cache=cache),
        )

        # assert
        assert code == 0
        assert "\x1b[2mskipped 'y': at-limit\x1b[0m" in out

    def test_a_preserved_unmanaged_login_reads_dim(self, tmp_path: Path):
        # arrange — the live slot holds a foreign login, not a managed account
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        slot = FakeActiveSlot(credentials=_creds_for("foreign"), config=_config_for("acc-foreign"))

        # act
        code, out, _ = _run_tty(
            ["switch", "x"], _use_cases(tmp_path, store=store, reader=reader, slot=slot)
        )

        # assert
        assert code == 0
        assert (
            "\x1b[2mthe previous unmanaged login was preserved under "
            "/unclaimed/fake-1.json\x1b[0m" in out
        )

    def test_a_quarantined_wiped_credential_reads_yellow(self, tmp_path: Path):
        # arrange — x's live tokens were wiped in place by an invalid_grant
        store = InMemoryAccountStore(tmp_path)
        reader = FakeAccountDir()
        _park(store, reader, "x")
        reader.delete_credentials(store.account_dir(AccountName("x")))
        store.set_active(AccountName("x"))
        _park(store, reader, "y")
        wiped = {"claudeAiOauth": {"accessToken": "", "refreshToken": "", "expiresAt": 1}}
        slot = FakeActiveSlot(credentials=wiped, config=_config_for("acc-x"))

        # act
        code, out, _ = _run_tty(
            ["switch", "y"], _use_cases(tmp_path, store=store, reader=reader, slot=slot)
        )

        # assert
        assert code == 0
        assert "\x1b[33mquarantined the wiped credential of 'x'\x1b[0m" in out
