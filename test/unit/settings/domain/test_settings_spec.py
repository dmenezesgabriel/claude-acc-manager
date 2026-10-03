"""Unit tests for settings.domain.settings_spec.

The dual-discipline contract: forgiving clamp on load, strict validation on
explicit user input, one SETTING_SPECS table as the source of truth for
both.
"""

import pytest

from claude_acc_manager.settings.domain.settings_spec import (
    SETTING_SPECS,
    AutoSettings,
    clamped_auto_settings,
    format_setting_value,
    parse_setting_value,
    setting_spec,
    strict_override,
)


class TestDefaults:
    def test_defaults_match_the_architecture_contract(self):
        settings = AutoSettings()
        assert settings.threshold == 90.0
        assert settings.interval_seconds == 60.0
        assert settings.cooldown_seconds == 300.0
        assert settings.hysteresis_pct == 10.0
        assert settings.strategy == "best"

    def test_specs_cover_every_field(self):
        fields = {spec.field for spec in SETTING_SPECS.values()}
        assert fields == {
            "threshold",
            "interval_seconds",
            "cooldown_seconds",
            "hysteresis_pct",
            "strategy",
        }


class TestClampedAutoSettings:
    def test_empty_section_gives_defaults(self):
        assert clamped_auto_settings({}) == AutoSettings()

    def test_in_range_values_load_verbatim(self):
        settings = clamped_auto_settings(
            {
                "threshold": 80,
                "intervalSeconds": 30,
                "cooldownSeconds": 0,
                "hysteresisPct": 5.5,
                "strategy": "next-available",
            }
        )
        assert settings.threshold == 80.0
        assert settings.interval_seconds == 30.0
        assert settings.cooldown_seconds == 0.0
        assert settings.hysteresis_pct == 5.5
        assert settings.strategy == "next-available"

    def test_out_of_range_clamps_into_bounds(self):
        settings = clamped_auto_settings({"threshold": 12, "intervalSeconds": 99999})
        assert settings.threshold == 50.0
        assert settings.interval_seconds == 3600.0

    def test_wrong_types_fall_back_to_defaults(self):
        settings = clamped_auto_settings(
            {"threshold": "high", "intervalSeconds": [60], "cooldownSeconds": None}
        )
        assert settings.threshold == 90.0
        assert settings.interval_seconds == 60.0
        assert settings.cooldown_seconds == 300.0

    def test_bool_is_not_a_number(self):
        # bool is a subclass of int — a literal true must not load as 1.0.
        assert clamped_auto_settings({"threshold": True}).threshold == 90.0

    def test_unknown_choice_falls_back_to_default(self):
        assert clamped_auto_settings({"strategy": "consume-first"}).strategy == "best"

    def test_unknown_keys_are_ignored(self):
        settings = clamped_auto_settings({"threshold": 80, "futureKnob": {"x": 1}})
        assert settings.threshold == 80.0

    def test_partial_section_keeps_defaults_elsewhere(self):
        settings = clamped_auto_settings({"threshold": 70})
        assert settings.interval_seconds == 60.0
        assert settings.strategy == "best"


class TestSettingSpec:
    def test_lookup_returns_the_spec(self):
        spec = setting_spec("autoswitch.threshold")
        assert spec.field == "threshold"
        assert spec.dotted == "autoswitch.threshold"

    def test_unknown_key_raises_with_the_valid_list(self):
        with pytest.raises(
            ValueError,
            match=r"unknown setting 'autoswitch\.bogus'\n"
            r"Valid keys: autoswitch\.threshold, autoswitch\.intervalSeconds",
        ):
            setting_spec("autoswitch.bogus")


class TestParseSettingValue:
    def test_float_parses(self):
        spec = setting_spec("autoswitch.threshold")
        assert parse_setting_value(spec, "80") == 80.0

    def test_float_out_of_range_raises(self):
        spec = setting_spec("autoswitch.threshold")
        with pytest.raises(ValueError, match="must be between 50 and 99.9"):
            parse_setting_value(spec, "120")

    def test_boundary_values_parse(self):
        spec = setting_spec("autoswitch.threshold")
        assert parse_setting_value(spec, "50") == 50.0
        assert parse_setting_value(spec, "99.9") == 99.9

    def test_non_numeric_raises(self):
        spec = setting_spec("autoswitch.threshold")
        with pytest.raises(ValueError, match="expects a number"):
            parse_setting_value(spec, "high")

    def test_choice_parses(self):
        spec = setting_spec("autoswitch.strategy")
        assert parse_setting_value(spec, "next-available") == "next-available"

    def test_choice_out_of_set_raises(self):
        spec = setting_spec("autoswitch.strategy")
        with pytest.raises(ValueError, match="must be one of: best, next-available"):
            parse_setting_value(spec, "rotate")


class TestStrictOverride:
    def test_in_range_override_applies(self):
        merged = strict_override(AutoSettings(), {"threshold": 75.0})
        assert merged.threshold == 75.0

    def test_multiple_overrides_all_apply(self):
        # A break on the first field would leave strategy untouched.
        merged = strict_override(AutoSettings(), {"threshold": 75.0, "strategy": "next-available"})
        assert merged.threshold == 75.0
        assert merged.strategy == "next-available"

    def test_boundary_overrides_apply(self):
        merged = strict_override(AutoSettings(), {"threshold": 50.0})
        assert merged.threshold == 50.0
        merged = strict_override(AutoSettings(), {"threshold": 99.9})
        assert merged.threshold == 99.9

    def test_out_of_range_override_raises_not_clamps(self):
        # Explicit user input errors loudly — only file values are forgiven.
        with pytest.raises(ValueError, match="must be between 50 and 99.9"):
            strict_override(AutoSettings(), {"threshold": 10.0})

    def test_non_number_override_raises(self):
        with pytest.raises(ValueError, match="expects a number"):
            strict_override(AutoSettings(), {"threshold": "high"})

    def test_bool_override_is_not_a_number(self):
        with pytest.raises(ValueError, match="expects a number"):
            strict_override(AutoSettings(), {"threshold": True})

    def test_unknown_field_override_raises(self):
        with pytest.raises(ValueError, match="unknown setting field 'bogus'"):
            strict_override(AutoSettings(), {"bogus": 1.0})

    def test_bad_choice_override_raises(self):
        with pytest.raises(ValueError, match="must be one of: best, next-available"):
            strict_override(AutoSettings(), {"strategy": "rotate"})

    def test_choice_override_applies(self):
        merged = strict_override(AutoSettings(), {"strategy": "next-available"})
        assert merged.strategy == "next-available"


class TestFormatSettingValue:
    def test_integral_floats_render_without_decimal(self):
        assert format_setting_value(80.0) == "80"

    def test_fractional_floats_render_as_float(self):
        assert format_setting_value(80.5) == "80.5"

    def test_str_renders_verbatim(self):
        assert format_setting_value("best") == "best"
