"""Cross-transport severity-ramp edges — the thresholds CLI and TUI share.

The CLI maps these onto named ANSI severities so its ramp adapts to the
terminal's own theme; the TUI maps them onto its hex ramp
(``tui/theme.py``). Keeping the edges here means a bar's color and the
auto-switch default threshold cannot drift apart.
"""

# Severity band edges. WARN mirrors where a user starts caring; CRIT mirrors
# the auto-switch default threshold so bar color and switch behavior agree.
WARN_PCT = 70.0
CRIT_PCT = 90.0
