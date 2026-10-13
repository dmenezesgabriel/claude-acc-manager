"""``cam doctor`` — the diagnostics report over faked probes.

User-facing output is pinned exactly — the printed line *is* the interface
(docs/architecture.md §10), so a drift in wording is a regression, not cosmetic.
"""

from pathlib import Path

import pytest
from support.cli_rigs import run_cli as _run
from support.cli_rigs import run_cli_tty as _run_tty
from support.fake_diagnostics import FakeDiagnostics, facts
from support.use_cases import make_use_cases

from claude_acc_manager.accounts.application.doctor_report import LockObservation
from claude_acc_manager.accounts.application.use_cases.collect_doctor_report import (
    CollectDoctorReport,
)
from claude_acc_manager.shared.claude_contract import contract_for_version

_use_cases = make_use_cases


class TestDoctorCommand:
    def test_renders_all_sections_and_exits_0(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange / act
        code = _run(["doctor"], _use_cases(tmp_path))

        # assert — fixed section order; findings don't gate the exit code
        assert code == 0
        out = capsys.readouterr().out
        sections = ["cam", "claude contract", "paths", "locks", "environment", "terminal", "system"]
        positions = [out.index(f"\n{s}\n" if i else f"{s}\n") for i, s in enumerate(sections)]
        assert positions == sorted(positions)

    def test_an_unsupported_contract_is_a_fail_row_and_still_exits_0(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange — a claude newer than the verified band
        diagnostics = CollectDoctorReport(
            FakeDiagnostics(facts(contract=contract_for_version((2, 2, 0)))),
            cam_version="0.0.0-test",
        )

        # act
        code = _run(["doctor"], _use_cases(tmp_path, diagnostics=diagnostics))

        # assert — doctor shows the refusal reason instead of refusing
        assert code == 0
        assert "contract: [FAIL]" in capsys.readouterr().out

    def test_verdict_badges_carry_severity_on_a_tty(self, tmp_path: Path):
        # arrange — held lock + assumed contract exercise warn; fail needs
        # an out-of-band claude
        diagnostics = CollectDoctorReport(
            FakeDiagnostics(
                facts(
                    contract=contract_for_version((2, 2, 0)),
                    locks=(LockObservation("oauth", Path("/a"), "held", 5.0),),
                )
            ),
            cam_version="0.0.0-test",
        )

        # act
        code, out, _ = _run_tty(["doctor"], _use_cases(tmp_path, diagnostics=diagnostics))

        # assert
        assert code == 0
        assert "\x1b[31m[FAIL]\x1b[0m" in out
        assert "\x1b[33m[WARN]\x1b[0m" in out
        assert "\x1b[32m[OK]\x1b[0m" in out
