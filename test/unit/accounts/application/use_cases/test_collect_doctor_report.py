"""CollectDoctorReport — facts to a sectioned, verdict-carrying report."""

from pathlib import Path

from support.fake_diagnostics import FakeDiagnostics, facts

from claude_acc_manager.accounts.application.doctor_report import LockObservation
from claude_acc_manager.accounts.application.use_cases.collect_doctor_report import (
    CollectDoctorReport,
)
from claude_acc_manager.shared.claude_contract import (
    CAM_ASSUME_CLAUDE_CONTRACT,
    ClaudeContract,
    contract_for_version,
)


def collect(facts_kwargs: dict[str, object] | None = None) -> object:
    """Run the use case over canned facts; kwargs steer the fake."""
    report = CollectDoctorReport(
        FakeDiagnostics(facts(**(facts_kwargs or {}))), cam_version="1.2.3"
    ).execute()
    return report


def checks(report: object, section: str) -> dict[str, object]:
    """The named section's rows as a {name: check} map."""
    for s in report.sections:  # type: ignore[attr-defined]
        if s.title == section:
            return {c.name: c for c in s.checks}
    raise AssertionError(f"section {section!r} missing")


class TestSections:
    def test_all_seven_sections_render_in_prd_order(self):
        # arrange / act
        report = collect()

        # assert
        titles = [s.title for s in report.sections]  # type: ignore[attr-defined]
        assert titles == [
            "cam",
            "claude contract",
            "paths",
            "locks",
            "environment",
            "terminal",
            "system",
        ]

    def test_the_injected_cam_version_leads_the_report(self):
        # arrange / act
        report = collect()

        # assert
        version = checks(report, "cam")["version"]
        assert version.value == "1.2.3"
        assert version.status == "info"


class TestContractVerdict:
    def test_a_supported_claude_is_an_ok_row(self):
        # arrange / act
        report = collect()

        # assert — the version row reports, the contract row verdicts
        section = checks(report, "claude contract")
        assert section["claude --version"].value == "2.1.288"
        assert section["claude --version"].status == "info"
        assert section["contract"].status == "ok"
        assert section["contract"].value == "supported — verified band 2.1.144–2.2.0 (exclusive)"

    def test_a_missing_claude_version_reports_not_found(self):
        # arrange — the probe found no claude binary
        not_found = ClaudeContract(version=None, supported=True, assumed=True, reason=None)
        report = collect({"contract": not_found})

        # assert
        section = checks(report, "claude contract")
        assert section["claude --version"].value == "not found"

    def test_an_out_of_band_claude_is_a_fail_row(self):
        # arrange — 2.2.0 is newer than the verified band
        report = collect({"contract": contract_for_version((2, 2, 0))})

        # assert
        check = checks(report, "claude contract")["contract"]
        assert check.status == "fail"
        assert "newer" in check.value

    def test_an_assumed_contract_is_a_warn_row(self):
        # arrange
        assumed = ClaudeContract(version=(2, 1, 288), supported=True, assumed=True, reason=None)
        report = collect({"contract": assumed})

        # assert — the verdict names the bypass var and still shows the band
        check = checks(report, "claude contract")["contract"]
        assert check.status == "warn"
        assert CAM_ASSUME_CLAUDE_CONTRACT in check.value
        assert "2.1.144–2.2.0 (exclusive)" in check.value

    def test_an_unsupported_contract_without_reason_says_so(self):
        # arrange — a reason-less out-of-band verdict
        unsupported = ClaudeContract(version=(2, 2, 0), supported=False, assumed=False, reason=None)
        report = collect({"contract": unsupported})

        # assert
        check = checks(report, "claude contract")["contract"]
        assert check.status == "fail"
        assert check.value == "unsupported"


class TestFacts:
    def test_a_missing_store_warns(self):
        # arrange / act
        report = collect({"store_exists": False})

        # assert
        check = checks(report, "cam")["store"]
        assert check.status == "warn"
        assert check.value == "/store (missing)"

    def test_a_present_store_is_an_ok_row(self):
        # arrange / act
        report = collect()

        # assert — just the path, no parenthetical
        check = checks(report, "cam")["store"]
        assert check.status == "ok"
        assert check.value == "/store"

    def test_paths_report_presence_verbatim(self):
        # arrange / act
        report = collect({"credentials_present": False, "accounts_dir_exists": False})

        # assert — path, space, parenthetical; every row named
        paths = checks(report, "paths")
        assert paths["credentials"].value == "/home/.claude/.credentials.json (absent)"
        assert paths["config"].value == "/home/.claude.json (present)"
        assert paths["accounts dir"].value == "/store/accounts (absent)"
        for row in paths.values():
            assert row.status == "info"

    def test_paths_all_present_when_the_files_exist(self):
        # arrange / act — the default fake has everything present
        report = collect()

        # assert — the present branch, row by row
        paths = checks(report, "paths")
        assert paths["credentials"].value == "/home/.claude/.credentials.json (present)"
        assert paths["config"].value == "/home/.claude.json (present)"
        assert paths["accounts dir"].value == "/store/accounts (present)"

    def test_lock_states_carry_their_verdict(self):
        # arrange — one of each state
        locks = (
            LockObservation("oauth refresh", Path("/a.lock"), "free", None),
            LockObservation("config", Path("/b.lock"), "held", 5.0),
            LockObservation("storage write", Path("/c"), "stale", 120.0),
        )
        report = collect({"locks": locks})

        # assert — "state (path)" values, free ok / held+stale warn
        rows = checks(report, "locks")
        assert rows["oauth refresh"].status == "ok"
        assert rows["oauth refresh"].value == "free (/a.lock)"
        assert rows["config"].status == "warn"
        assert rows["config"].value == "held (/b.lock)"
        assert rows["storage write"].status == "warn"
        assert rows["storage write"].value == "stale (/c)"

    def test_the_contract_bypass_env_var_warns_when_set(self):
        # arrange / act
        report = collect({"env": {CAM_ASSUME_CLAUDE_CONTRACT: "1"}})

        # assert — set shows the value and warns; unset shows "unset" info
        env = checks(report, "environment")
        assert env[CAM_ASSUME_CLAUDE_CONTRACT].status == "warn"
        assert env[CAM_ASSUME_CLAUDE_CONTRACT].value == "1"
        assert env["CLAUDE_CONFIG_DIR"].status == "info"
        assert env["CLAUDE_CONFIG_DIR"].value == "unset"
        assert env["XDG_DATA_HOME"].value == "unset"
        assert env["CLAUDE_SECURESTORAGE_CONFIG_DIR"].value == "unset"

    def test_env_rows_echo_their_set_values(self):
        # arrange / act — the default fake env carries TERM/COLORTERM only
        report = collect({"env": {"CLAUDE_CONFIG_DIR": "/scoped"}})

        # assert — only the bypass var escalates; ordinary vars stay info
        env = checks(report, "environment")
        assert env["CLAUDE_CONFIG_DIR"].value == "/scoped"
        assert env["CLAUDE_CONFIG_DIR"].status == "info"
        assert env[CAM_ASSUME_CLAUDE_CONTRACT].value == "unset"

    def test_terminal_facts_report_tts_and_interactivity(self):
        # arrange / act
        report = collect({"stdout_tty": False, "interactive": False})

        # assert — per-stream tty words plus the combined verdict
        term = checks(report, "terminal")
        assert term["stdin"].value == "tty"
        assert term["stdout"].value == "not a tty"
        assert term["interactive"].value == "no"
        for row in term.values():
            assert row.status == "info"

    def test_terminal_env_vars_echo_or_report_unset(self):
        # arrange / act — default fake env: TERM+COLORTERM set, NO_COLOR absent
        report = collect()

        # assert — default fake: both streams ttys, TERM+COLORTERM set
        term = checks(report, "terminal")
        assert term["stdin"].value == "tty"
        assert term["stdout"].value == "tty"
        assert term["interactive"].value == "yes"
        assert term["TERM"].value == "xterm-256color"
        assert term["COLORTERM"].value == "truecolor"
        assert term["NO_COLOR"].value == "unset"

    def test_system_carries_platform_and_privilege_facts(self):
        # arrange / act
        report = collect({"euid": 0, "in_container": True})

        # assert
        system = checks(report, "system")
        assert system["euid"].value == "0"
        assert system["container"].value == "yes"
        assert "3.12" in system["python"].value

    def test_system_defaults_report_host_facts(self):
        # arrange / act
        report = collect()

        # assert
        system = checks(report, "system")
        assert system["python"].value == "CPython 3.12.0"
        assert system["platform"].value == "Linux-6.0-test"
        assert system["euid"].value == "1000"
        assert system["container"].value == "no"
