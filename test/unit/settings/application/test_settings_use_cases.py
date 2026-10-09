"""Unit tests for the settings use cases over an in-memory SettingsPort."""

from pathlib import Path

import pytest
from support.in_memory_settings import InMemorySettings

from claude_acc_manager.settings.application.use_cases.list_settings import ListSettings
from claude_acc_manager.settings.application.use_cases.load_privacy_settings import (
    LoadPrivacySettings,
)
from claude_acc_manager.settings.application.use_cases.load_settings import LoadSettings
from claude_acc_manager.settings.application.use_cases.set_setting import SetSetting
from claude_acc_manager.settings.application.use_cases.unset_setting import UnsetSetting
from claude_acc_manager.settings.domain.settings_spec import (
    SETTING_SPECS,
    AutoSettings,
    PrivacySettings,
)


class TestLoadSettings:
    def test_returns_the_port_settings(self, tmp_path: Path):
        # arrange / act / assert
        assert LoadSettings(InMemorySettings(tmp_path)).execute() == AutoSettings()

    def test_reflects_set_values(self, tmp_path: Path):
        # arrange
        settings = InMemorySettings(tmp_path)
        SetSetting(settings).execute("autoswitch.threshold", "80")

        # act / assert
        assert LoadSettings(settings).execute().threshold == 80.0


class TestLoadPrivacySettings:
    def test_defaults_on_a_fresh_store(self, tmp_path: Path):
        # arrange / act / assert
        assert LoadPrivacySettings(InMemorySettings(tmp_path)).execute() == PrivacySettings()

    def test_reflects_set_values(self, tmp_path: Path):
        # arrange
        settings = InMemorySettings(tmp_path)
        SetSetting(settings).execute("privacy.redactEmails", "false")

        # act / assert
        assert LoadPrivacySettings(settings).execute().redact_emails is False


class TestSetSetting:
    def test_validates_and_stores(self, tmp_path: Path):
        # arrange / act
        value = SetSetting(InMemorySettings(tmp_path)).execute("autoswitch.intervalSeconds", "45")

        # assert
        assert value == 45.0

    def test_unknown_key_raises(self, tmp_path: Path):
        # arrange / act / assert
        with pytest.raises(ValueError, match="unknown setting"):
            SetSetting(InMemorySettings(tmp_path)).execute("autoswitch.bogus", "1")

    def test_bad_value_raises_and_writes_nothing(self, tmp_path: Path):
        # arrange
        settings = InMemorySettings(tmp_path)

        # act / assert
        with pytest.raises(ValueError, match="expects a number"):
            SetSetting(settings).execute("autoswitch.threshold", "high")
        assert settings.load().threshold == 90.0

    def test_bool_value_round_trips_as_a_real_bool(self, tmp_path: Path):
        # arrange / act
        value = SetSetting(InMemorySettings(tmp_path)).execute("privacy.redactEmails", "false")

        # assert — the stored value is a JSON-style bool, not the string
        assert value is False


class TestUnsetSetting:
    def test_removes_a_set_key(self, tmp_path: Path):
        # arrange
        settings = InMemorySettings(tmp_path)
        SetSetting(settings).execute("autoswitch.threshold", "80")

        # act
        removed = UnsetSetting(settings).execute("autoswitch.threshold")

        # assert
        assert removed is True
        assert settings.load().threshold == 90.0

    def test_unset_unset_key_is_false(self, tmp_path: Path):
        # arrange / act / assert
        assert UnsetSetting(InMemorySettings(tmp_path)).execute("autoswitch.threshold") is False


class TestListSettings:
    def test_lists_every_spec_key(self, tmp_path: Path):
        # arrange / act
        rows = ListSettings(InMemorySettings(tmp_path)).execute()

        # assert
        assert {row.spec.dotted for row in rows} == set(SETTING_SPECS)

    def test_marks_explicitly_set_keys(self, tmp_path: Path):
        # arrange — an explicit value equal to the default still counts as set
        settings = InMemorySettings(tmp_path)
        SetSetting(settings).execute("autoswitch.threshold", "90")

        # act
        rows = ListSettings(settings).execute()

        # assert
        threshold = next(row for row in rows if row.spec.field == "threshold")
        assert threshold.is_set is True
        others = [row for row in rows if row.spec.field != "threshold"]
        assert all(not row.is_set for row in others)
