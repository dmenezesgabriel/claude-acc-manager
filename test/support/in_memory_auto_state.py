"""In-memory AutoStatePort fake for hermetic engine tests."""

from collections.abc import Generator
from contextlib import contextmanager

from claude_acc_manager.auto.application.ports import AutoStatePort
from claude_acc_manager.auto.domain.auto_state import EMPTY_AUTO_STATE, AutoState


class InMemoryAutoState(AutoStatePort):
    """AutoStatePort backed by a field — no lock, no file."""

    def __init__(self, state: AutoState = EMPTY_AUTO_STATE) -> None:
        """Start at *state* (EMPTY_AUTO_STATE by default)."""
        self._state = state
        self.lock_holds = 0

    def load(self) -> AutoState:
        """The current in-memory state."""
        return self._state

    @contextmanager
    def locked(self) -> Generator[None]:
        """A no-op hold that still counts acquisitions for assertions."""
        self.lock_holds += 1
        yield

    def save(self, state: AutoState) -> None:
        """Record *state* (contract: only valid under ``locked()``)."""
        self._state = state
