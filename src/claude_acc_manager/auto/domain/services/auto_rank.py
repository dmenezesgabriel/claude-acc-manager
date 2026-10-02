"""auto_rank — pure trigger/cooldown/ranking logic for the auto engine.

Ports the reference auto-switcher's decision core (claude-swap
``autoswitch.py``) minus the deferred axes (consume-first, failover,
api-key, model-scoped windows): trigger classification, the cooldown
predicate, the headroom and all-exhausted recovery rankings, and the
simplified no-return guard that refuses to undo the engine's own move
until the account it left has genuinely recovered.

Everything here is pure — no ports, no I/O. The engine feeds it
snapshots, headroom, and state; it answers with names and verdicts.

Example:
    ordered, any_known = choose("proactive", candidates=["a", "b"], ...)
"""

import math
from collections.abc import Mapping, Sequence
from typing import Literal

from claude_acc_manager.auto.domain.auto_state import AutoState
from claude_acc_manager.settings.domain.settings_spec import AutoStrategy
from claude_acc_manager.usage.domain.services.headroom import relevant_windows
from claude_acc_manager.usage.domain.services.poll_policy import (
    limiting_reset_epoch,
    parse_reset_epoch,
)
from claude_acc_manager.usage.domain.usage_snapshot import UsageSnapshot

Trigger = Literal["below", "proactive", "at-limit"]

# Anti-flap margins, ported from the reference: hysteresis in seconds on the
# recovery axis, a ratio plus an absolute floor on the headroom axis, and a
# horizon past which a sooner reset stops being worth real headroom.
RECOVERY_HYSTERESIS_S = 300.0
RECOVERY_HORIZON_S = 4 * 3600.0
HORIZON_HEADROOM_RATIO = 2.0
SPENT_HEADROOM_PCT = 3.0


def classify_trigger(active_headroom: float | None, threshold: float) -> Trigger | None:
    """What the active account's utilization demands, or None when unknown.

    ``below`` stays put without ranking; ``proactive`` escapes before the
    wall under the anti-flap gates; ``at-limit`` is the escape that skips
    them. None is "active usage unknown" — M9 has no failover axis, so the
    engine maps it to no-action.

    Example:
        classify_trigger(20.0, 90.0) == "below"
    """
    if active_headroom is None:
        return None
    if (100.0 - active_headroom) < threshold:
        return "below"
    return "at-limit" if active_headroom <= 0 else "proactive"


def in_cooldown(state: AutoState, now_s: float, cooldown_s: float) -> bool:
    """Whether a recorded switch still sits inside the cooldown window.

    Example:
        in_cooldown(state, now_s=1700000000.0, cooldown_s=300.0)
    """
    if state.last_switch_at_s is None:
        return False
    return now_s - state.last_switch_at_s < cooldown_s


def binding_recovery_epoch(snapshot: UsageSnapshot | None, now_s: float) -> float:
    """When this account's *binding* window resets, as a sort key.

    The binding window is the one holding the account back — the highest
    utilization among the relevant windows (the same set ``account_headroom``
    measures). ``inf`` when unknown or already past, so such accounts sort
    last rather than masquerading as "back immediately".

    Example:
        binding_recovery_epoch(snapshot, now_s=1700000000.0)
    """
    windows = relevant_windows(snapshot)
    if not windows:
        return math.inf
    _label, _pct, resets_at = max(windows, key=lambda w: w[1])
    epoch = parse_reset_epoch(resets_at)
    return epoch if epoch is not None and epoch > now_s else math.inf


def every_account_above_threshold(
    candidates: Sequence[str],
    headroom: Mapping[str, float | None],
    active_headroom: float | None,
    threshold: float,
) -> bool:
    """Whether the active account AND every measured candidate are at/over.

    The state where "land somewhere healthy" has no answer and the recovery
    axis takes over. An unmeasured candidate does not block the verdict; an
    unknown active defeats it (we can't know we're in this state).

    Example:
        every_account_above_threshold(["a"], {"a": 5.0}, 4.0, 90.0)
    """
    if active_headroom is None or (100.0 - active_headroom) < threshold:
        return False
    measured = [h for h in map(headroom.get, candidates) if h is not None]
    return bool(measured) and all((100.0 - h) >= threshold for h in measured)


def recovery_is_useful(
    candidate_recovery_ts: float,
    active_recovery_ts: float,
    active_headroom: float,
    best_candidate_headroom: float,
    now_s: float,
) -> bool:
    """Rank THIS candidate by soonest reset rather than by headroom?

    The axis is a property of the pair, not the candidate alone — keying it
    on the candidate flips the axis mid-move and lets a pair straddling the
    horizon take one gate out and the other back. Either side inside
    ``RECOVERY_HORIZON_S`` selects the recovery axis; so does a fleet where
    everything worth having is spent (below ``SPENT_HEADROOM_PCT`` a
    headroom edge is under two poll intervals of work).

    Example:
        recovery_is_useful(ts_a, ts_b, 3.0, 5.0, now_s)
    """
    if active_headroom <= SPENT_HEADROOM_PCT and best_candidate_headroom <= SPENT_HEADROOM_PCT:
        return True
    return (
        candidate_recovery_ts - now_s <= RECOVERY_HORIZON_S
        or active_recovery_ts - now_s <= RECOVERY_HORIZON_S
    )


def left_account_recovered(
    state: AutoState,
    headroom: Mapping[str, float | None],
    snapshots: Mapping[str, UsageSnapshot | None],
    threshold: float,
    now_s: float,
) -> bool:
    """Is the account we left better than when we left it?

    The release the no-return bar needs and the ranking cannot supply —
    the distinction is between the present and the moment of departure.
    Three legs, each with the margin its axis already uses: the landing
    floor (``h > 100 - threshold`` — would the ranking accept it now),
    ``+SPENT_HEADROOM_PCT`` over the departure headroom baseline, and a
    binding reset improved by ``RECOVERY_HYSTERESIS_S``. Absence of a
    departure record releases (no evidence either way).

    Example:
        left_account_recovered(state, headroom, snapshots, 90.0, now)
    """
    if state.last_switch_from is None:
        return True
    barred = state.last_switch_from
    h = headroom.get(barred)
    if h is not None and h > 100.0 - threshold:
        return True
    if state.left_headroom is not None and h is not None:
        if h >= state.left_headroom + SPENT_HEADROOM_PCT:
            return True
    was = state.left_recovery_at_s if state.left_recovery_at_s is not None else math.inf
    return binding_recovery_epoch(snapshots.get(barred), now_s) < was - RECOVERY_HYSTERESIS_S


def no_return_account(
    trigger: Trigger,
    state: AutoState,
    current: str | None,
    headroom: Mapping[str, float | None],
    snapshots: Mapping[str, UsageSnapshot | None],
    active_headroom: float | None,
    threshold: float,
    now_s: float,
) -> str | None:
    """The account this engine most recently left, while it is still barred.

    Scoped to ``proactive`` — ``at-limit`` is an escape and must never be
    barred (a 2-account fleet on an exhausted active would strand). Scoped
    to the engine's own landing: a manual move off ``last_switch_to``
    already undid the move, so the bar protects nothing. Released when the
    left account has recovered AND now beats the active by the anti-flap
    ratio — that return is a move on its own merits, not a flip.

    Example:
        no_return_account("proactive", state, "c", headroom, snaps, 3.0, 90.0, now)
    """
    came_from = state.last_switch_from
    if trigger != "proactive" or came_from is None:
        return None
    if state.last_switch_to is not None and current is not None and state.last_switch_to != current:
        return None
    if _bar_released(state, came_from, headroom, snapshots, active_headroom, threshold, now_s):
        return None
    return came_from


def _bar_released(
    state: AutoState,
    came_from: str,
    headroom: Mapping[str, float | None],
    snapshots: Mapping[str, UsageSnapshot | None],
    active_headroom: float | None,
    threshold: float,
    now_s: float,
) -> bool:
    """Whether the barred account earned release — recovered AND better outright."""
    if not left_account_recovered(state, headroom, snapshots, threshold, now_s):
        return False
    left_headroom = headroom.get(came_from)
    if left_headroom is None:
        return False
    if active_headroom is not None:
        return left_headroom >= active_headroom * HORIZON_HEADROOM_RATIO
    return left_headroom > 100.0 - threshold


def rank_candidates(
    trigger: Trigger,
    candidates: Sequence[str],
    snapshots: Mapping[str, UsageSnapshot | None],
    headroom: Mapping[str, float | None],
    active: str,
    active_headroom: float | None,
    threshold: float,
    hysteresis_pct: float,
    strategy: AutoStrategy,
    now_s: float,
    no_return: str | None,
) -> tuple[list[str], bool]:
    """Filter and rank candidates for this tick's trigger.

    ``(ordered, any_known)``. *candidates* arrive eligible (enabled,
    unquarantined, credentialed) in registry order, active excluded.
    ``proactive`` requires a below-threshold landing plus the strategy
    margin — unless every measured account is over, where the goal flips
    to "soonest back" and hysteresis runs on the recovery axis instead.

    Example:
        rank_candidates("proactive", ["a", "b"], snaps, headroom, "c", 5.0, ...)
    """
    all_above = every_account_above_threshold(candidates, headroom, active_headroom, threshold)
    census = _fleet_census(candidates, snapshots, headroom, active, now_s)
    qualifying: list[tuple[tuple[float, ...], str]] = []
    fallback: list[tuple[tuple[float, ...], str]] = []
    any_known = False
    # The bar is scoped to proactive — at-limit is an escape, and refusing it
    # strands a 2-account fleet on an exhausted active (reference measured).
    barred = no_return if trigger == "proactive" else None
    for index, name in enumerate(candidates):
        h = headroom.get(name)
        if h is None:
            continue
        any_known = True
        admission = _admission(
            trigger,
            all_above,
            name,
            h,
            barred,
            snapshots.get(name),
            active_headroom,
            census[0],
            census[1],
            threshold,
            hysteresis_pct,
            strategy,
            now_s,
            index,
        )
        if admission is not None:
            (fallback if admission[1] else qualifying).append((admission[0], name))
    pool = qualifying or fallback
    pool.sort(key=lambda t: t[0])
    return [name for _, name in pool], any_known


def _fleet_census(
    candidates: Sequence[str],
    snapshots: Mapping[str, UsageSnapshot | None],
    headroom: Mapping[str, float | None],
    active: str,
    now_s: float,
) -> tuple[float, list[float]]:
    """The two fleet-wide inputs every candidate's gate shares.

    Returns ``(active_recovery_ts, measured candidate headrooms)``. The
    list is read through ``max`` only under all_above — which implies at
    least one measured candidate — so it may safely be empty here.
    """
    measured = [h for h in map(headroom.get, candidates) if h is not None]
    return binding_recovery_epoch(snapshots.get(active), now_s), measured


def choose(
    trigger: Trigger,
    *,
    candidates: Sequence[str],
    snapshots: Mapping[str, UsageSnapshot | None],
    headroom: Mapping[str, float | None],
    active: str,
    active_headroom: float | None,
    threshold: float,
    hysteresis_pct: float,
    strategy: AutoStrategy,
    state: AutoState,
    now_s: float,
) -> tuple[list[str], bool]:
    """Rank with the no-return bar applied, released when it empties the list.

    The release asks the one question the ranking cannot — did the account
    we left actually recover — because "barred leaves nothing" and "we are
    flapping" look identical to a single snapshot. Only a recovered left
    account re-ranks unbarred.

    Example:
        choose("proactive", candidates=["a"], ..., state=state, now_s=now)
    """
    no_return = no_return_account(
        trigger, state, active, headroom, snapshots, active_headroom, threshold, now_s
    )
    ranked = rank_candidates(
        trigger,
        candidates,
        snapshots,
        headroom,
        active,
        active_headroom,
        threshold,
        hysteresis_pct,
        strategy,
        now_s,
        no_return,
    )
    if (
        # Dropping this conjunct re-ranks with no_return=None — the same call
        # pass 1 already made when no bar exists — a fixed point, so the
        # conjunct's absence is unobservable.
        no_return is not None  # pragma: no mutate
        and not ranked[0]
        and left_account_recovered(state, headroom, snapshots, threshold, now_s)
    ):
        return rank_candidates(
            trigger,
            candidates,
            snapshots,
            headroom,
            active,
            active_headroom,
            threshold,
            hysteresis_pct,
            # The re-rank only ever adds back the one barred name — pass 2
            # changes nothing for every other candidate, so the list is ≤1
            # and the ordering strategy is unobservable here.
            strategy,  # pragma: no mutate
            now_s,
            None,
        )
    return ranked


def earliest_recovery_epoch(
    snapshots: Mapping[str, UsageSnapshot | None], now_s: float
) -> float | None:
    """Earliest moment any account becomes usable again, or None.

    Per account that's the latest reset among its ≥100% relevant windows —
    an account blocked on two windows isn't usable when the first rolls
    over — then the minimum across accounts. A blocked account whose
    exhausted windows carry no provable reset makes the whole answer
    unprovable: None, so the caller falls back to the bounded blocked
    cadence instead of oversleeping.

    Example:
        earliest_recovery_epoch(snapshots, now_s=1700000000.0)
    """
    earliest: float | None = None
    for snapshot in snapshots.values():
        if snapshot is None:
            continue
        if not any(pct >= 100.0 for _, pct, _ in relevant_windows(snapshot)):
            continue  # not exhausted — doesn't gate the blocked state
        usable_at = limiting_reset_epoch(snapshot)
        if usable_at is None or usable_at <= now_s:
            return None  # blocked with unprovable recovery — don't oversleep
        # `<`→`<=` reassigns an equal value — the stored float is unchanged.
        if earliest is None or usable_at < earliest:  # pragma: no mutate
            earliest = usable_at
    return earliest


def _strategy_key(strategy: AutoStrategy, index: int, h: float) -> tuple[float, ...]:
    """The ordinary sort key: registry order for rotation, headroom for best."""
    return (float(index),) if strategy == "next-available" else (-h,)


def _admission(
    trigger: Trigger,
    all_above: bool,
    name: str,
    h: float,
    barred: str | None,
    snapshot: UsageSnapshot | None,
    active_headroom: float | None,
    active_recovery_ts: float,
    candidate_headrooms: Sequence[float],
    threshold: float,
    hysteresis_pct: float,
    strategy: AutoStrategy,
    now_s: float,
    index: int,
) -> tuple[tuple[float, ...], bool] | None:
    """The sort key for an admissible candidate, or None to refuse it.

    ``(key, is_fallback)`` — the fallback pool re-admits spent-band margin
    failures only when nothing else qualifies. ``at-limit`` skips every
    anti-flap gate: escaping a dead account, any real headroom qualifies.
    """
    if h <= 0 or name == barred:
        return None
    if trigger != "proactive":
        # A False→True flip here lands the whole cohort in the fallback pool
        # uniformly — `qualifying or fallback` then yields the same list.
        return _strategy_key(strategy, index, h), False  # pragma: no mutate
    if not all_above:
        return _healthy_landing(h, active_headroom, threshold, hysteresis_pct, strategy, index)
    if active_headroom is None:
        return None  # unreachable — all_above implies a measured active
    return _all_spent_admission(
        h,
        snapshot,
        active_headroom,
        active_recovery_ts,
        candidate_headrooms,
        now_s,
    )


def _healthy_landing(
    h: float,
    active_headroom: float | None,
    threshold: float,
    hysteresis_pct: float,
    strategy: AutoStrategy,
    index: int,
) -> tuple[tuple[float, ...], bool] | None:
    """Proactive gates while a healthy landing exists: below-threshold + margin."""
    if (100.0 - h) >= threshold:
        return None  # landing at/over the threshold re-triggers next tick
    if strategy == "best" and active_headroom is not None and h - active_headroom < hysteresis_pct:
        return None
    # See _admission — a uniform flag flip is pool-invariant.
    return _strategy_key(strategy, index, h), False  # pragma: no mutate


def _all_spent_admission(
    h: float,
    snapshot: UsageSnapshot | None,
    active_headroom: float,
    active_recovery_ts: float,
    candidate_headrooms: Sequence[float],
    now_s: float,
) -> tuple[tuple[float, ...], bool] | None:
    """Recovery-axis gates when every measured account is at/over threshold.

    Which axis each candidate ranks by is decided by ``recovery_is_useful``
    — see its docstring for the axis-leak walk. Both axes carry the
    reference's own anti-flap margin: hysteresis on resets, the ratio plus
    spent fallback on headroom.
    """
    recovery_ts = binding_recovery_epoch(snapshot, now_s)
    if recovery_is_useful(
        recovery_ts,
        active_recovery_ts,
        active_headroom,
        max(candidate_headrooms),
        now_s,
    ):
        if recovery_ts >= active_recovery_ts - RECOVERY_HYSTERESIS_S:
            return None
        return (0.0, recovery_ts, -h), False
    if h < active_headroom * HORIZON_HEADROOM_RATIO:
        return _spent_fallback(h, recovery_ts, active_headroom, active_recovery_ts)
    # The tier constant only has to exceed the recovery tier (0.0); within the
    # qualifying pool its magnitude is rank-invariant.
    return (1.0, -h, recovery_ts), False  # pragma: no mutate


def _spent_fallback(
    h: float,
    recovery_ts: float,
    active_headroom: float,
    active_recovery_ts: float,
) -> tuple[tuple[float, ...], bool] | None:
    """Re-admit a margin failure only when both sides are spent and it returns sooner."""
    if (
        active_headroom <= SPENT_HEADROOM_PCT
        and h >= active_headroom
        and recovery_ts < active_recovery_ts - RECOVERY_HYSTERESIS_S
    ):
        # The fallback pool is homogeneous — every entry carries the recovery
        # key, so a leading tier constant would be inert here.
        return (recovery_ts, -h), True
    return None
