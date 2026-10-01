"""The switch-outcome wording — one render shared by every surface.

The CLI prints it verbatim and embeds it as the JSON ``message``; the TUI
toasts it. Both import from here so the phrasing cannot drift.
"""

from claude_acc_manager.accounts.application.use_cases.switch_account import SwitchResult

_STAY_MESSAGES: dict[str, str] = {
    "no-valid-target": "no valid switch target",
    "candidates-exhausted": "every candidate is at its limit",
    "usage-unavailable": "usage unknown — cannot rank candidates",
    "already-best": "the active account already has the most headroom",
}


def switch_message(result: SwitchResult) -> str:
    """The one-line render of a switch outcome.

    Example:
        ``switch_message(result) == "switched to 'work' (was 'personal')"``
    """
    prefix = "dry run: " if result.dry_run else ""
    if result.outcome == "switched":
        return f"{prefix}switched to {result.target!r} (was {_switch_from(result)})"
    if result.outcome == "already-active":
        return f"{prefix}{result.target!r} is already the active account"
    return f"{prefix}{_STAY_MESSAGES[result.outcome]}"


def _switch_from(result: SwitchResult) -> str:
    """The outgoing side of a switch line: a name, an unmanaged login, or none."""
    if result.previous is not None:
        return repr(result.previous)
    if result.unmanaged_live:
        return "an unmanaged login"
    return "no login"
