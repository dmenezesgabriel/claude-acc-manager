"""The "cam-dark"/"cam-light" Textual themes and shared color constants.

A subtle modern dark theme: neutral charcoal backgrounds, one warm
terracotta accent (a deliberate nod to Claude Code's orange, used
sparingly), and desaturated severity colors so usage bars read calmly.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.theme import Theme

# ACCENT / MUTED / WARN_PCT / CRIT_PCT live in shared/palette.py — the CLI
# maps the same edges onto named ANSI severities (SL-014).
from claude_acc_manager.shared.palette import ACCENT, CRIT_PCT, MUTED, WARN_PCT

# Core palette (single source of truth — widgets import these for rich
# renderables, the Theme below maps them onto Textual's design tokens).
FOREGROUND = "#e8e4de"  # soft, slightly warm off-white
BACKGROUND = "#141414"
SURFACE = "#1e1e1e"
PANEL = "#262626"

# Usage severity ramp (desaturated for dark backgrounds).
SEV_OK = "#87af87"  # calm green: plenty of headroom
SEV_WARN = "#d7af5f"  # amber: climbing (>= 70%)
SEV_CRIT = "#d75f5f"  # soft red: near the limit (>= 90%)
TRACK = "#3a3a3a"  # unfilled bar track


@dataclass(frozen=True)
class Palette:
    """Resolved colors for Rich renderables, keyed to a Textual theme.

    Rich renderables bake color into styles at render time, so they can't
    read Textual's ``$variables`` the way the .tcss layer does. A Palette
    carries the active theme's colors so the same render code paints
    correctly in either theme. Resolve from the Theme object (never
    App.theme_variables, which lags the deferred CSS refresh).
    """

    accent: str
    foreground: str
    muted: str
    sev_ok: str
    sev_warn: str
    sev_crit: str
    track: str

    def severity(self, pct: float | None) -> str:
        """The ramp color for a utilization percent (muted when unknown)."""
        if pct is None:
            return self.muted
        if pct >= CRIT_PCT:
            return self.sev_crit
        if pct >= WARN_PCT:
            return self.sev_warn
        return self.sev_ok

    @classmethod
    def from_theme(cls, theme: Theme) -> Palette:
        """Resolve the palette for *theme* — e.g. ``Palette.from_theme(CAM_DARK)``.

        Unset theme tokens (``None``) fall back to the dark constants — a
        palette must always carry concrete colors.
        """
        return cls(
            accent=theme.primary or ACCENT,
            foreground=theme.foreground or FOREGROUND,
            muted=theme.secondary or MUTED,
            sev_ok=theme.success or SEV_OK,
            sev_warn=theme.warning or SEV_WARN,
            sev_crit=theme.error or SEV_CRIT,
            track=theme.variables.get("track") or TRACK,
        )


CAM_DARK = Theme(
    name="cam-dark",
    primary=ACCENT,
    secondary=MUTED,
    accent=ACCENT,
    foreground=FOREGROUND,
    background=BACKGROUND,
    surface=SURFACE,
    panel=PANEL,
    success=SEV_OK,
    warning=SEV_WARN,
    error=SEV_CRIT,
    dark=True,
    variables={
        # Footer keys pick up the accent instead of the default blue.
        "footer-key-foreground": ACCENT,
        "block-cursor-background": PANEL,
        "block-cursor-foreground": FOREGROUND,
        "block-cursor-text-style": "none",
        "track": TRACK,
    },
)

# Light companion palette (same intent, tuned for a warm near-white base).
ACCENT_LIGHT = "#954c2a"  # burnt sienna — deepened for AA on panel
FOREGROUND_LIGHT = "#2b2723"
MUTED_LIGHT = "#635d55"
BACKGROUND_LIGHT = "#faf7f2"
SURFACE_LIGHT = "#efeae1"
PANEL_LIGHT = "#e2dbcf"  # most-elevated = darkest (inverted from dark)
SEV_OK_LIGHT = "#3d6b3d"  # forest green — deepened for AA on panel
SEV_WARN_LIGHT = "#795911"  # deep ochre — deepened for AA on panel
SEV_CRIT_LIGHT = "#ad3128"  # brick red — deepened for AA on panel
TRACK_LIGHT = "#cec7ba"

CAM_LIGHT = Theme(
    name="cam-light",
    primary=ACCENT_LIGHT,
    secondary=MUTED_LIGHT,
    accent=ACCENT_LIGHT,
    foreground=FOREGROUND_LIGHT,
    background=BACKGROUND_LIGHT,
    surface=SURFACE_LIGHT,
    panel=PANEL_LIGHT,
    success=SEV_OK_LIGHT,
    warning=SEV_WARN_LIGHT,
    error=SEV_CRIT_LIGHT,
    dark=False,
    variables={
        "footer-key-foreground": ACCENT_LIGHT,
        "block-cursor-background": PANEL_LIGHT,
        "block-cursor-foreground": FOREGROUND_LIGHT,
        "block-cursor-text-style": "none",
        "track": TRACK_LIGHT,
    },
)
