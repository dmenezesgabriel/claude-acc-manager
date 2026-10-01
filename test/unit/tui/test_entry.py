"""The lazy TUI entry point.

``run()`` stays import-light for the CLI paths that never open the TUI —
the tests swap ``CamApp`` for a recorder rather than owning a terminal.
"""

from pathlib import Path

import pytest
from support.use_cases import make_use_cases

import claude_acc_manager.tui.app as tui_app
from claude_acc_manager.tui import run


@pytest.fixture(name="built")
def _built_app(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Swap CamApp for a recorder and return the captured wiring."""
    captured: dict[str, object] = {}

    class FakeCamApp:
        """Records construction and reports a chosen return code."""

        def __init__(self, use_cases: object, *, start: str) -> None:
            """Capture the wiring; the real app would own the terminal."""
            self.ran = False
            self.return_code = captured.pop("code", None)
            captured.update(use_cases=use_cases, start=start, app=self)

        def run(self) -> None:
            """Pretend the UI ran."""
            self.ran = True

    monkeypatch.setattr(tui_app, "CamApp", FakeCamApp)
    return captured


class TestRun:
    def test_run_builds_the_app_on_the_dashboard_by_default(
        self, tmp_path: Path, built: dict[str, object]
    ) -> None:
        use_cases = make_use_cases(tmp_path)

        code = run(use_cases)

        assert code == 0
        assert built["use_cases"] is use_cases
        assert built["start"] == "dashboard"
        assert built["app"].ran is True

    def test_run_passes_the_watch_start_through(
        self, tmp_path: Path, built: dict[str, object]
    ) -> None:
        code = run(make_use_cases(tmp_path), start="watch")

        assert built["start"] == "watch"
        assert code == 0

    @pytest.mark.parametrize(("return_code", "expected"), [(None, 0), (2, 2)])
    def test_run_returns_the_apps_exit_code(
        self,
        tmp_path: Path,
        built: dict[str, object],
        return_code: int | None,
        expected: int,
    ) -> None:
        built["code"] = return_code

        assert run(make_use_cases(tmp_path)) == expected
