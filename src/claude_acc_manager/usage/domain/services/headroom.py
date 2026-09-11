"""Remaining quota headroom over a usage snapshot's binding windows.

Evidence: claude-swap ``oauth.py`` ``account_headroom``/``relevant_windows``
(read directly, cross-checked against its ``tests/test_oauth.py``
``TestAccountHeadroom``/``TestRelevantWindows``). The 5-hour and 7-day
windows always gate requests; a named model-scoped weekly window (e.g.
"Fable") binds just as hard for someone pinned to that model, so it folds
into the same ``max()`` when *models* names it. ``headroom = 100 -
max(pct)``; ``None`` means "unknown", which every caller must treat as
unknown, never as "exhausted" (plan §4.5) — this is the same "missing data
never invents a number" discipline as ``usage_snapshot.py``.

Example:
    account_headroom(snapshot, models=("Fable",))
"""

from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot

RelevantWindow = tuple[str, float, str | None]


def relevant_windows(
    snapshot: UsageSnapshot | None, models: tuple[str, ...] = ()
) -> tuple[RelevantWindow, ...]:
    """Every ``(label, pct, resets_at)`` window that gates this account.

    Always the 5-hour ("5h") and 7-day ("7d") windows when present. When
    *models* is non-empty, each named per-model weekly ``scoped`` window is
    included too (case-insensitive; ``"all"`` matches every scoped window).
    The single canonical window source for both headroom and poll-cadence
    decisions, so a window that binds one can never be invisible to the
    other.

    Example:
        relevant_windows(snapshot, models=("Fable",))
    """
    if snapshot is None:
        return ()
    windows: list[RelevantWindow] = []
    if snapshot.five_hour is not None:
        windows.append(("5h", snapshot.five_hour.pct, snapshot.five_hour.resets_at))
    if snapshot.seven_day is not None:
        windows.append(("7d", snapshot.seven_day.pct, snapshot.seven_day.resets_at))
    if models:
        wanted = {model.lower() for model in models}
        match_all = "all" in wanted
        for window in snapshot.scoped:
            if match_all or window.name.lower() in wanted:
                windows.append((window.name, window.pct, window.resets_at))
    return tuple(windows)


def account_headroom(snapshot: UsageSnapshot | None, models: tuple[str, ...] = ()) -> float | None:
    """Remaining percentage before this account hits a binding window.

    Returns ``100 - max(pct)`` over :func:`relevant_windows`, so ``<= 0``
    means the account is at or over a limit. Returns ``None`` when no
    relevant window carries data — callers must treat that as "unknown",
    never as "exhausted" (an unmeasurable account is never auto-skipped).

    Example:
        account_headroom(snapshot) == 20.0
    """
    pcts = [pct for _, pct, _ in relevant_windows(snapshot, models)]
    if not pcts:
        return None
    return 100.0 - max(pcts)
