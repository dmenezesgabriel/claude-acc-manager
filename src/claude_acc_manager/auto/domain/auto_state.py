"""AutoState — the engine's persisted memory between ticks and processes.

Carries the cooldown stamp and the departure snapshot the no-return guard
needs: which account we left, what its headroom was at departure, and when
its binding reset was expected. ``leftRecoveryAt`` is None when the left
account's recovery couldn't be measured (no usable reset known).

Quarantine is deliberately NOT here — it lives in the account registry's
fingerprint-bound tombstones (ADR-0009) so `cam list` and the engine agree.

Example:
    AutoState(last_switch_at_s=1700000000.0, last_switch_from="work",
              left_headroom=12.5, left_recovery_at_s=1700003600.0)
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AutoState:
    """One recorded switch's cooldown and no-return data; all-None means never."""

    last_switch_at_s: float | None = None
    last_switch_from: str | None = None
    left_headroom: float | None = None
    left_recovery_at_s: float | None = None


EMPTY_AUTO_STATE = AutoState()
