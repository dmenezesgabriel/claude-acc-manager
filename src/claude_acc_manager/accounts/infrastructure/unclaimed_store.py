"""Adapter implementing UnclaimedCredentialPort under ``<store>/unclaimed/``.

A live credential whose login matches no registered account is never dropped:
the switch preserves it here, as one wrapped envelope carrying the reason it
was displaced and both files' contents. Envelopes are named by capture time
(sanitized ISO) with ``.1``, ``.2``, … collision suffixes — same convention as
salvage_torn_config.

Example:
    store = FileUnclaimedStore(Path("~/.local/share/claude-acc-manager"), clock)
    path = store.preserve(creds, config, "foreign")
"""

from pathlib import Path

from claude_acc_manager.accounts.application.ports import (
    ClockPort,
    UnclaimedCredentialPort,
)
from claude_acc_manager.shared import fsio


class FileUnclaimedStore(UnclaimedCredentialPort):
    """UnclaimedCredentialPort writing wrapped envelopes under unclaimed/.

    Example:
        path = FileUnclaimedStore(Path("/store"), clock).preserve(c, None, "x")
    """

    def __init__(self, store_root: Path, clock: ClockPort) -> None:
        """Keep the store root and the clock that stamps each envelope."""
        self._root = store_root
        self._clock = clock

    def preserve(
        self,
        credentials: dict[str, object],
        config: dict[str, object] | None,
        reason: str,
    ) -> Path:
        """Write the (credentials, config) pair under ``unclaimed/``.

        The envelope records *reason* (``unmanaged``/``foreign``/``wiped``)
        and the capture timestamp so a later session can tell displaced
        logins apart without opening the credential body.
        """
        captured_at = self._clock.now_iso()
        envelope = {
            "reason": reason,
            "captured_at": captured_at,
            "credentials": credentials,
            "config": config,
        }
        path = self._next_path(captured_at)
        fsio.atomic_write_json(path, envelope)
        return path

    def _next_path(self, captured_at: str) -> Path:
        """First free ``unclaimed/<stamp>.json``; ``:`` → ``-`` keeps it portable."""
        stamp = captured_at.replace(":", "-")
        unclaimed = self._root / "unclaimed"
        candidate = unclaimed / f"{stamp}.json"
        n = 1
        while candidate.exists():
            candidate = unclaimed / f"{stamp}.{n}.json"
            n += 1  # pragma: no mutate — same argument as salvage_torn_config's loop
        return candidate
