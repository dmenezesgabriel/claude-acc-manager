"""Ports for the auto component — boundaries the engine and use cases drive."""

from contextlib import AbstractContextManager
from typing import Literal, Protocol

from claude_acc_manager.auto.domain.auto_state import AutoState

FreshenStatus = Literal["ok", "dead", "transient"]
"""Freshen verdicts: safe to activate / lineage dead (quarantine) / retry later."""


class FreshenPort(Protocol):
    """The engine-facing seam for proving a candidate's parked credential is alive.

    ``FreshenTarget`` satisfies it structurally — the port exists so the
    engine depends on the capability, not the use-case class (AGENTS: a use
    case never depends on another use case).

    Example:
        if freshen.execute("personal") == "ok": ...
    """

    def execute(self, account_key: str) -> FreshenStatus:
        """``"ok"`` when the account's credential is fit to activate right now."""
        ...


class AutoStatePort(Protocol):
    """Persistence boundary for the engine's cooldown + no-return memory.

    ``locked()`` holds the dedicated ``.auto-state.lock`` across a whole
    recheck → switch → record sequence so a concurrent engine (loop +
    cron ``--once``) makes one serialized decision — never the store's
    shared ``.lock``, which the switch itself takes (self-deadlock).

    ``save`` must be called under ``locked()``; it does not lock itself
    (flock is not reentrant — a second flock on the same file would block
    forever).

    Example:
        with auto_state.locked():
            state = auto_state.load()
            if in_cooldown(state, now, cooldown_s):
                return NO_ACTION
            switch_executor.execute("personal")
            auto_state.save(replace(state, last_switch_at_s=now))
    """

    def load(self) -> AutoState:
        """The persisted state, or EMPTY_AUTO_STATE when never written."""
        ...

    def locked(self) -> AbstractContextManager[None]:
        """An exclusive hold on the state file for a read-check-write span."""
        ...

    def save(self, state: AutoState) -> None:
        """Atomically persist *state*; only valid under ``locked()``."""
        ...
