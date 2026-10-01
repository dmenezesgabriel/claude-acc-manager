"""Severity bands and theme resolution for the TUI palette."""

from claude_acc_manager.tui.theme import CAM_DARK, CAM_LIGHT, Palette

_PALETTE = Palette.from_theme(CAM_DARK)


class TestPaletteSeverity:
    """The three-band ramp: warn at 70, crit at 90, muted when unknown."""

    def test_none_is_muted(self) -> None:
        assert _PALETTE.severity(None) == _PALETTE.muted

    def test_below_warn_is_ok(self) -> None:
        assert _PALETTE.severity(69.9) == _PALETTE.sev_ok

    def test_warn_edge(self) -> None:
        assert _PALETTE.severity(70.0) == _PALETTE.sev_warn

    def test_mid_band_stays_warn(self) -> None:
        assert _PALETTE.severity(89.9) == _PALETTE.sev_warn

    def test_crit_edge(self) -> None:
        assert _PALETTE.severity(90.0) == _PALETTE.sev_crit


class TestFromTheme:
    """A Palette resolved off a Textual Theme mirrors the theme's tokens."""

    def test_dark_theme_tokens(self) -> None:
        palette = Palette.from_theme(CAM_DARK)
        assert palette.accent == CAM_DARK.primary
        assert palette.foreground == CAM_DARK.foreground
        assert palette.muted == CAM_DARK.secondary
        assert palette.sev_ok == CAM_DARK.success
        assert palette.sev_warn == CAM_DARK.warning
        assert palette.sev_crit == CAM_DARK.error
        assert palette.track == CAM_DARK.variables["track"]

    def test_light_theme_tokens(self) -> None:
        # the `or` fallbacks must defer to a theme that sets every token —
        # an `and` mutant would return the constant for a populated theme
        palette = Palette.from_theme(CAM_LIGHT)
        assert palette.accent == CAM_LIGHT.primary
        assert palette.sev_ok == CAM_LIGHT.success
        assert palette.sev_crit == CAM_LIGHT.error
        assert palette.track == CAM_LIGHT.variables["track"]

    def test_light_resolves_to_different_colors(self) -> None:
        assert Palette.from_theme(CAM_LIGHT).sev_ok != Palette.from_theme(CAM_DARK).sev_ok

    def test_themes_are_named_for_the_app(self) -> None:
        assert CAM_DARK.name == "cam-dark" and CAM_DARK.dark
        assert CAM_LIGHT.name == "cam-light" and not CAM_LIGHT.dark
