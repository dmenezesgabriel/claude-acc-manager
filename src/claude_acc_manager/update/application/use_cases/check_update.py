"""CheckUpdate use case — is there a newer cam on PyPI, answered cheaply.

The command surfaces (stderr notice, TUI toast, auto event line) all ask
the same question; this is the one place that answers it. Two hard rules,
both claude-swap's: the check is advisory and **never raises** — a dead
index or a torn cache can never break the command that triggered it — and
a failure is cached like a success, so a dead network costs one 2s probe
per interval, not one per command.

``CAM_DISABLE_UPDATE_CHECK`` (non-empty) kills the check outright;
``updates.mode off`` does the same through settings. A current version
that is not a final release — the ``0.0.0+local`` dev checkout, a
prerelease — never asks at all: there is nothing to compare against.

Example:
    check = CheckUpdate(feed, cache, clock, mode="notify", env=os.environ,
                        current_version=package_version())
    offer = check.execute()  # UpdateOffer | None
"""

from collections.abc import Mapping

from claude_acc_manager.settings.domain.settings_spec import UpdateMode
from claude_acc_manager.update.application.ports import (
    ReleaseFeedPort,
    UpdateCheckCachePort,
    UpdateCheckRecord,
)
from claude_acc_manager.update.domain.services.version_order import (
    is_newer,
    parse_release,
    release_type,
)
from claude_acc_manager.update.domain.update_offer import UpdateOffer
from claude_acc_manager.usage.application.ports import ClockPort

__all__ = ["CheckUpdate", "UpdateOffer"]

CAM_DISABLE_UPDATE_CHECK = "CAM_DISABLE_UPDATE_CHECK"
# claude-swap's 24h: releases land rarely, so probing more often buys nothing.
CHECK_INTERVAL_S = 86_400.0


class CheckUpdate:
    """Answer "is there a newer release" at most once per interval.

    Example:
        offer = CheckUpdate(feed, cache, clock, mode="notify", env={},
                            current_version="1.1.0").execute()
    """

    def __init__(
        self,
        feed: ReleaseFeedPort,
        cache: UpdateCheckCachePort,
        clock: ClockPort,
        *,
        mode: UpdateMode,
        env: Mapping[str, str],
        current_version: str,
    ) -> None:
        """Store the injected ports and the resolved policy inputs.

        *mode* arrives already loaded (``LoadUpdateSettings`` at the
        composition root), matching how ``FetchAccountUsage`` receives
        ``threshold`` — the use case stays free of the settings port.
        """
        self._feed = feed
        self._cache = cache
        self._clock = clock
        self._mode = mode
        self._env = env
        self._current_version = current_version

    def execute(self) -> UpdateOffer | None:
        """The newer release worth reporting, or None — never raises for I/O.

        Gates, cheapest first: the env kill-switch, ``updates.mode off``,
        and a non-release current version. ``auto`` behaves exactly like
        ``notify`` here — escalating a patch offer into an upgrade is the
        surface's job downstream (SelfUpgrade), not the check's.
        """
        if self._env.get(CAM_DISABLE_UPDATE_CHECK):
            return None
        if self._mode == "off":
            return None
        if parse_release(self._current_version) is None:
            return None
        latest = self._latest()
        if latest is None or not is_newer(self._current_version, latest):
            return None
        return UpdateOffer(
            current_version=self._current_version,
            latest_version=latest,
            release_type=release_type(self._current_version, latest),
        )

    def _latest(self) -> str | None:
        """The newest release the index reported — cache-first, failure-cached.

        Every I/O edge degrades rather than raises: a torn cache reads as
        "never checked" (FileUpdateCheckCache fails loud by its own
        contract — that discipline stops at this boundary, a corrupt file
        must not reach the user's command), a feed failure is cached as
        ``latest_version=None`` so a dead index is not repolled, and an
        unwritable cache still returns the fetched answer.
        """
        now = self._clock.now_epoch_s()
        try:
            record = self._cache.load()
        except Exception:
            record = None
        if record is not None and now - record.checked_at_s < CHECK_INTERVAL_S:
            return record.latest_version
        try:
            latest = self._feed.latest_version()
        except Exception:
            latest = None
        try:
            self._cache.save(UpdateCheckRecord(checked_at_s=now, latest_version=latest))
        except Exception:
            pass
        return latest
