"""Cross-transport palette constants — one severity ramp for CLI and TUI.

The TUI renders these hexes verbatim (dark/light themes pick their own
companion set); the CLI maps the same edges onto named ANSI severities so
its ramp adapts to the terminal's own theme instead of assuming a dark
background.
"""

ACCENT = "#d7875f"  # warm terracotta (xterm 173)
MUTED = "#8a8a8a"  # secondary text

# Severity band edges. WARN mirrors where a user starts caring; CRIT mirrors
# the auto-switch default threshold so bar color and switch behavior agree.
WARN_PCT = 70.0
CRIT_PCT = 90.0
