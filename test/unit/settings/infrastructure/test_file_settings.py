"""Unit tests for settings.infrastructure.file_settings."""

import json
import os
import stat
from pathlib import Path

import pytest

from claude_acc_manager.settings.domain.settings_spec import SETTING_SPECS, setting_spec
from claude_acc_manager.settings.infrastructure.file_settings import FileSettings


def _write(store_root: Path, document: object) -> Path:
    store_root.mkdir(parents=True, exist_ok=True)
    path = store_root / "settings.json"
    path.write_text(json.dumps(document))
    return path


class TestLoad:
    def test_missing_file_gives_defaults(self, tmp_path: Path):
        # arrange / act / assert
        settings = FileSettings(tmp_path).load()
        assert settings.threshold == 90.0

    def test_valid_section_loads(self, tmp_path: Path):
        # arrange
        _write(tmp_path, {"schemaVersion": 1, "autoswitch": {"threshold": 80}})

        # act
        settings = FileSettings(tmp_path).load()

        # assert
        assert settings.threshold == 80.0

    def test_torn_file_loads_defaults(self, tmp_path: Path):
        # arrange — user-editable file: a bad hand edit degrades, never crashes
        _write(tmp_path, {})
        (tmp_path / "settings.json").write_text("{ not json")

        # act / assert
        assert FileSettings(tmp_path).load().threshold == 90.0

    def test_non_object_file_loads_defaults(self, tmp_path: Path):
        # arrange
        _write(tmp_path, [1, 2, 3])

        # act / assert
        assert FileSettings(tmp_path).load().threshold == 90.0

    def test_non_object_section_loads_defaults(self, tmp_path: Path):
        # arrange
        _write(tmp_path, {"schemaVersion": 1, "autoswitch": "nope"})

        # act / assert
        assert FileSettings(tmp_path).load().threshold == 90.0


class TestLoadPrivacy:
    def test_missing_file_gives_defaults(self, tmp_path: Path):
        # arrange / act / assert
        assert FileSettings(tmp_path).load_privacy().redact_emails is True

    def test_stored_bool_loads(self, tmp_path: Path):
        # arrange
        _write(tmp_path, {"schemaVersion": 1, "privacy": {"redactEmails": False}})

        # act / assert
        assert FileSettings(tmp_path).load_privacy().redact_emails is False

    def test_non_object_section_loads_defaults(self, tmp_path: Path):
        # arrange
        _write(tmp_path, {"schemaVersion": 1, "privacy": "nope"})

        # act / assert
        assert FileSettings(tmp_path).load_privacy().redact_emails is True

    def test_wrong_type_loads_defaults(self, tmp_path: Path):
        # arrange — 1 is an int, not a bool
        _write(tmp_path, {"schemaVersion": 1, "privacy": {"redactEmails": 1}})

        # act / assert
        assert FileSettings(tmp_path).load_privacy().redact_emails is True

    def test_set_writes_a_real_json_bool(self, tmp_path: Path):
        # arrange / act
        FileSettings(tmp_path).set_value(setting_spec("privacy.redactEmails"), False)

        # assert — the file carries a JSON boolean, not the string "false"
        document = json.loads((tmp_path / "settings.json").read_text())
        assert document == {"schemaVersion": 1, "privacy": {"redactEmails": False}}


class TestSet:
    def test_set_writes_the_key_and_version(self, tmp_path: Path):
        # arrange / act
        FileSettings(tmp_path).set_value(setting_spec("autoswitch.threshold"), 80.0)

        # assert
        document = json.loads((tmp_path / "settings.json").read_text())
        assert document == {"schemaVersion": 1, "autoswitch": {"threshold": 80.0}}

    def test_set_preserves_unknown_keys_and_sections(self, tmp_path: Path):
        # arrange
        _write(
            tmp_path,
            {
                "schemaVersion": 1,
                "autoswitch": {"threshold": 80, "futureKnob": 7},
                "ui": {"theme": "dark"},
            },
        )

        # act
        FileSettings(tmp_path).set_value(setting_spec("autoswitch.strategy"), "next-available")

        # assert
        document = json.loads((tmp_path / "settings.json").read_text())
        assert document["autoswitch"]["futureKnob"] == 7
        assert document["autoswitch"]["strategy"] == "next-available"
        assert document["ui"] == {"theme": "dark"}

    def test_set_on_torn_file_raises_instead_of_overwriting(self, tmp_path: Path):
        # arrange — the forgiving load would hide a torn file; the write path
        # must not start a read-modify-write from {} and destroy it
        _write(tmp_path, {})
        (tmp_path / "settings.json").write_text("{ not json")

        # act / assert
        with pytest.raises(ValueError, match="is not valid JSON .*fix or delete it first"):
            FileSettings(tmp_path).set_value(setting_spec("autoswitch.threshold"), 80.0)
        assert (tmp_path / "settings.json").read_text() == "{ not json"

    def test_set_on_non_object_file_raises(self, tmp_path: Path):
        # arrange
        _write(tmp_path, [1])

        # act / assert
        with pytest.raises(
            ValueError,
            match=r"is not a JSON object \(got list\); fix or delete it first",
        ):
            FileSettings(tmp_path).set_value(setting_spec("autoswitch.threshold"), 80.0)

    def test_written_file_is_private(self, tmp_path: Path):
        # arrange / act
        FileSettings(tmp_path).set_value(setting_spec("autoswitch.threshold"), 80.0)

        # assert
        mode = stat.S_IMODE(os.stat(tmp_path / "settings.json").st_mode)
        assert mode == 0o600

    def test_writes_take_the_store_shared_lock(self, tmp_path: Path):
        # arrange / act
        FileSettings(tmp_path).set_value(setting_spec("autoswitch.threshold"), 80.0)

        # assert — the shared .lock must exist: file_settings mutations race with
        # registry/usage-cache writes in the same store
        assert (tmp_path / ".lock").exists()


class TestUnset:
    def test_unset_removes_the_key(self, tmp_path: Path):
        # arrange
        settings = FileSettings(tmp_path)
        settings.set_value(setting_spec("autoswitch.threshold"), 80.0)

        # act
        removed = settings.unset_value(setting_spec("autoswitch.threshold"))

        # assert
        assert removed is True
        document = json.loads((tmp_path / "settings.json").read_text())
        assert document.get("autoswitch", {}) == {}

    def test_unset_drops_an_emptied_section(self, tmp_path: Path):
        # arrange
        settings = FileSettings(tmp_path)
        settings.set_value(setting_spec("autoswitch.threshold"), 80.0)
        settings.unset_value(setting_spec("autoswitch.threshold"))

        # act / assert — an emptied section key does not linger
        assert "autoswitch" not in json.loads((tmp_path / "settings.json").read_text())

    def test_unset_absent_key_is_false_and_writes_nothing(self, tmp_path: Path):
        # arrange / act
        removed = FileSettings(tmp_path).unset_value(setting_spec("autoswitch.threshold"))

        # assert
        assert removed is False
        assert not (tmp_path / "settings.json").exists()


class TestEffective:
    def test_rows_cover_every_spec(self, tmp_path: Path):
        # arrange / act
        rows = FileSettings(tmp_path).effective()

        # assert
        assert {row.spec.dotted for row in rows} == set(SETTING_SPECS)
        assert all(not row.is_set for row in rows)

    def test_set_key_is_flagged(self, tmp_path: Path):
        # arrange
        settings = FileSettings(tmp_path)
        settings.set_value(setting_spec("autoswitch.threshold"), 80.0)

        # act
        rows = settings.effective()

        # assert
        threshold = next(row for row in rows if row.spec.field == "threshold")
        assert threshold.is_set and threshold.value == 80.0

    def test_privacy_row_reflects_the_file(self, tmp_path: Path):
        # arrange
        _write(tmp_path, {"schemaVersion": 1, "privacy": {"redactEmails": False}})

        # act
        rows = FileSettings(tmp_path).effective()

        # assert
        privacy = next(row for row in rows if row.spec.field == "redact_emails")
        assert privacy.is_set and privacy.value is False


class TestPath:
    def test_path_points_at_settings_json(self, tmp_path: Path):
        # arrange / act / assert
        assert FileSettings(tmp_path).path == tmp_path / "settings.json"
