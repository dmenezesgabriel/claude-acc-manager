"""Ports for the auto component — boundaries the engine and use cases drive."""

from contextlib import AbstractContextManager
from typing import Protocol

from claude_acc_manager.auto.domain.auto_state import AutoState


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
