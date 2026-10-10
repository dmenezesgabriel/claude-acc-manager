"""Unit tests for update.application.use_cases.check_update.

The check's contract: cache-first (one probe per interval), failure-cached
(a dead index is not repolled every command), and never-raises — a check
that can break the tool is unacceptable (claude-swap's rule, adopted).
"""

import pytest
from support.controllable_clock import ControllableClock
from support.failable_update_cache import FailableUpdateCheckCache
from support.fake_release_feed import FakeReleaseFeed
from support.in_memory_update_cache import InMemoryUpdateCheckCache

from claude_acc_manager.update.application.ports import UpdateCheckRecord
from claude_acc_manager.update.application.use_cases.check_update import (
    CHECK_INTERVAL_S,
    CheckUpdate,
)
from claude_acc_manager.update.domain.services.version_order import ReleaseType
from claude_acc_manager.update.domain.update_offer import UpdateOffer

NOW = 1_760_000_000.0


def make_check(
    *,
    feed: FakeReleaseFeed | None = None,
    cache: InMemoryUpdateCheckCache | None = None,
    mode: str = "notify",
    env: dict[str, str] | None = None,
    current_version: str = "1.1.0",
) -> tuple[CheckUpdate, FakeReleaseFeed, InMemoryUpdateCheckCache]:
    """A CheckUpdate over named fakes at a pinned NOW (1.2.0 is newer by default)."""
    feed = feed if feed is not None else FakeReleaseFeed("1.2.0")
    cache = cache if cache is not None else InMemoryUpdateCheckCache()
    check = CheckUpdate(
        feed,
        cache,
        ControllableClock(NOW),
        mode=mode,
        env=env or {},
        current_version=current_version,
    )
    return check, feed, cache


def record(age_s: float, latest_version: str | None = "1.2.0") -> UpdateCheckRecord:
    """A check record *age_s* old at the pinned NOW."""
    return UpdateCheckRecord(checked_at_s=NOW - age_s, latest_version=latest_version)


class TestKillSwitches:
    def test_the_env_var_silences_the_check(self):
        # arrange / act
        check, feed, cache = make_check(env={"CAM_DISABLE_UPDATE_CHECK": "1"})

        # assert
        assert check.execute() is None
        assert feed.calls == 0
        assert cache.saves == []

    def test_an_empty_env_value_does_not_disable(self):
        # only a non-empty value counts (CAM_ASSUME_CLAUDE_CONTRACT precedent)
        # arrange / act
        check, feed, _ = make_check(env={"CAM_DISABLE_UPDATE_CHECK": ""})

        # assert
        assert check.execute() is not None
        assert feed.calls == 1

    def test_mode_off_never_checks(self):
        # arrange / act
        check, feed, cache = make_check(mode="off")

        # assert
        assert check.execute() is None
        assert feed.calls == 0
        assert cache.saves == []


class TestDevBuildsNeverAsk:
    @pytest.mark.parametrize("current", ["0.0.0+local", "1.2.0rc1", "unknown"])
    def test_a_non_release_current_version_skips_the_check(self, current: str):
        # 0.0.0+local is an unpacked checkout (package_version); a prerelease
        # or garbage string has no release to compare against — asking helps
        # no one, so neither a fetch nor a cache write happens
        # arrange / act
        check, feed, cache = make_check(current_version=current)

        # assert
        assert check.execute() is None
        assert feed.calls == 0
        assert cache.saves == []


class TestFreshCache:
    def test_a_fresh_record_serves_without_fetching(self):
        # arrange / act
        check, feed, _ = make_check(cache=InMemoryUpdateCheckCache(record(60.0)))
        offer = check.execute()

        # assert
        assert feed.calls == 0
        assert offer == UpdateOffer(
            current_version="1.1.0", latest_version="1.2.0", release_type=ReleaseType.MINOR
        )

    def test_a_record_just_inside_the_interval_is_still_fresh(self):
        # arrange / act
        check, feed, _ = make_check(cache=InMemoryUpdateCheckCache(record(CHECK_INTERVAL_S - 1.0)))
        offer = check.execute()

        # assert
        assert offer is not None
        assert feed.calls == 0

    def test_a_future_dated_record_is_trusted_as_fresh(self):
        # a clock ahead of the recorded check must not cause a fetch storm —
        # the negative age still lands inside the interval
        # arrange / act
        check, feed, _ = make_check(cache=InMemoryUpdateCheckCache(record(-3600.0)))
        offer = check.execute()

        # assert
        assert offer is not None
        assert feed.calls == 0

    def test_an_equal_cached_release_offers_nothing(self):
        # arrange / act
        check, feed, _ = make_check(
            cache=InMemoryUpdateCheckCache(record(60.0, latest_version="1.1.0"))
        )

        # assert
        assert check.execute() is None
        assert feed.calls == 0

    def test_a_cached_failure_is_not_retried_inside_the_interval(self):
        # the failure-caching rule the notice's budget rests on: a dead index
        # is not repolled on every command
        # arrange / act
        check, feed, _ = make_check(
            cache=InMemoryUpdateCheckCache(record(60.0, latest_version=None))
        )

        # assert
        assert check.execute() is None
        assert feed.calls == 0


class TestStaleOrMissingCache:
    @pytest.mark.parametrize("age_s", [CHECK_INTERVAL_S, CHECK_INTERVAL_S + 60.0])
    def test_a_record_at_or_past_the_interval_refetches(self, age_s: float):
        # arrange / act
        check, feed, cache = make_check(
            cache=InMemoryUpdateCheckCache(record(age_s, latest_version="1.1.0"))
        )

        # assert
        assert check.execute() is not None
        assert feed.calls == 1
        assert cache.saves == [UpdateCheckRecord(checked_at_s=NOW, latest_version="1.2.0")]

    def test_never_checked_fetches_and_caches_the_answer(self):
        # arrange / act
        check, feed, cache = make_check()
        offer = check.execute()

        # assert
        assert offer == UpdateOffer(
            current_version="1.1.0", latest_version="1.2.0", release_type=ReleaseType.MINOR
        )
        assert feed.calls == 1
        assert cache.saves == [UpdateCheckRecord(checked_at_s=NOW, latest_version="1.2.0")]

    def test_a_stale_answer_is_still_cached(self):
        # an equal answer refreshes the record too — otherwise every command
        # past the interval would refetch forever
        # arrange / act
        check, _, cache = make_check(feed=FakeReleaseFeed("1.1.0"))

        # assert
        assert check.execute() is None
        assert cache.saves == [UpdateCheckRecord(checked_at_s=NOW, latest_version="1.1.0")]


class TestNeverRaises:
    def test_a_feed_failure_returns_none_and_caches_it(self):
        # arrange / act
        check, _, cache = make_check(feed=FakeReleaseFeed(latest_version=None))

        # assert
        assert check.execute() is None
        assert cache.saves == [UpdateCheckRecord(checked_at_s=NOW, latest_version=None)]

    def test_a_raising_feed_is_swallowed_and_still_cached(self):
        # the port promises never-raises; the use case keeps its own promise
        # even against a misbehaving adapter
        # arrange / act
        check, feed, cache = make_check(feed=FakeReleaseFeed(error=RuntimeError("boom")))

        # assert
        assert check.execute() is None
        assert feed.calls == 1
        assert cache.saves == [UpdateCheckRecord(checked_at_s=NOW, latest_version=None)]

    def test_a_torn_cache_load_reads_as_never_checked(self):
        # FileUpdateCheckCache fails loud on drift by contract; the check
        # degrades that to a miss, not an error in the user's command
        # arrange
        cache = FailableUpdateCheckCache()
        cache.pin("load", RuntimeError("torn"))

        # act
        check, feed, _ = make_check(cache=cache)
        offer = check.execute()

        # assert
        assert offer is not None
        assert feed.calls == 1

    def test_a_failed_save_still_reports_the_offer(self):
        # arrange
        cache = FailableUpdateCheckCache()
        cache.pin("save", RuntimeError("read-only"))

        # act
        check, feed, _ = make_check(cache=cache)
        offer = check.execute()

        # assert — the fetch succeeded; only the persistence failed
        assert offer is not None
        assert cache.calls == ["load", "save"]


class TestAutoMode:
    def test_auto_runs_the_same_check_as_notify(self):
        # applying the patch upgrade is the surface's job (SelfUpgrade via
        # T6), not the check's — auto only differs downstream of execute()
        # arrange / act
        check, feed, _ = make_check(mode="auto")

        # assert
        assert check.execute() is not None
        assert feed.calls == 1
