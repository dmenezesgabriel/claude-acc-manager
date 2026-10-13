"""``cam config`` — the persisted settings surface through the dispatch layer."""

import json
from pathlib import Path

import pytest
from support.cli_rigs import run_cli as _run
from support.use_cases import make_use_cases

_use_cases = make_use_cases


class TestConfigCommand:
    """`cam config` — the persisted settings surface."""

    def test_bare_config_lists_all_keys_with_defaults_marked(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange / act
        code = _run(["config"], _use_cases(tmp_path))

        # assert
        out = capsys.readouterr().out
        assert code == 0
        assert "autoswitch.threshold" in out
        assert "90" in out
        assert "privacy.redactEmails" in out
        assert "updates.mode" in out
        assert out.count("(default)") == 7

    def test_list_marks_only_set_keys(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange
        use_cases = _use_cases(tmp_path)
        _run(["config", "set", "autoswitch.threshold", "80"], use_cases)
        capsys.readouterr()

        # act
        code = _run(["config", "list"], use_cases)

        # assert
        out = capsys.readouterr().out
        assert code == 0
        threshold_line = next(
            line for line in out.splitlines() if line.startswith("autoswitch.threshold")
        )
        assert "80" in threshold_line and "(default)" not in threshold_line
        assert out.count("(default)") == 6

    def test_get_prints_the_effective_value(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange / act
        code = _run(["config", "get", "autoswitch.threshold"], _use_cases(tmp_path))

        # assert
        assert code == 0
        assert capsys.readouterr().out.strip() == "90"

    def test_get_json_reports_is_set(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange
        use_cases = _use_cases(tmp_path)
        _run(["config", "set", "autoswitch.threshold", "80"], use_cases)
        capsys.readouterr()

        # act
        code = _run(["config", "get", "--json", "autoswitch.threshold"], use_cases)

        # assert
        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload == {
            "schemaVersion": 1,
            "key": "autoswitch.threshold",
            "value": 80.0,
            "isSet": True,
        }

    def test_list_json_wraps_every_key(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange / act
        code = _run(["config", "list", "--json"], _use_cases(tmp_path))

        # assert
        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload["schemaVersion"] == 1
        assert payload["path"].endswith("settings.json")
        keys = {row["key"] for row in payload["settings"]}
        assert keys == {
            "autoswitch.threshold",
            "autoswitch.intervalSeconds",
            "autoswitch.cooldownSeconds",
            "autoswitch.hysteresisPct",
            "autoswitch.strategy",
            "privacy.redactEmails",
            "updates.mode",
        }
        assert all(row["isSet"] is False for row in payload["settings"])
        values = {row["key"]: row["value"] for row in payload["settings"]}
        assert values == {
            "autoswitch.threshold": 90.0,
            "autoswitch.intervalSeconds": 60.0,
            "autoswitch.cooldownSeconds": 300.0,
            "autoswitch.hysteresisPct": 10.0,
            "autoswitch.strategy": "best",
            "privacy.redactEmails": True,
            "updates.mode": "notify",
        }

    def test_set_persists_and_confirms(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange
        use_cases = _use_cases(tmp_path)

        # act
        code = _run(["config", "set", "autoswitch.threshold", "80"], use_cases)

        # assert
        assert code == 0
        assert capsys.readouterr().out.strip() == "autoswitch.threshold = 80"
        assert use_cases.load_settings.execute().threshold == 80.0

    def test_set_unknown_key_errors(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange / act
        code = _run(["config", "set", "autoswitch.bogus", "1"], _use_cases(tmp_path))

        # assert
        assert code == 1
        assert "unknown setting" in capsys.readouterr().err

    def test_set_out_of_range_errors(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange / act
        code = _run(["config", "set", "autoswitch.threshold", "999"], _use_cases(tmp_path))

        # assert
        assert code == 1
        assert "between 50 and 99.9" in capsys.readouterr().err

    def test_unset_reverts_to_the_default(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        # arrange
        use_cases = _use_cases(tmp_path)
        _run(["config", "set", "autoswitch.threshold", "80"], use_cases)
        capsys.readouterr()

        # act
        code = _run(["config", "unset", "autoswitch.threshold"], use_cases)

        # assert
        assert code == 0
        assert "autoswitch.threshold unset (default: 90)" in capsys.readouterr().out
        assert use_cases.load_settings.execute().threshold == 90.0

    def test_unset_when_not_set_reports_nothing_to_do(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange / act
        code = _run(["config", "unset", "autoswitch.threshold"], _use_cases(tmp_path))

        # assert
        assert code == 0
        assert "is not set; nothing to do" in capsys.readouterr().err

    def test_path_prints_the_settings_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        # arrange / act
        code = _run(["config", "path"], _use_cases(tmp_path))

        # assert
        out = capsys.readouterr().out.strip()
        assert code == 0
        assert out.endswith("settings.json")
