"""Contract tests for the shared FakeReleaseFeed fake."""

import pytest
from support.fake_release_feed import FakeReleaseFeed

from claude_acc_manager.update.application.ports import ReleaseFeedPort


class TestFakeReleaseFeedAdaptsThePort:
    def test_is_a_release_feed_port(self):
        assert isinstance(FakeReleaseFeed(), ReleaseFeedPort)


class TestLatestVersion:
    def test_returns_the_pinned_version(self):
        # arrange / act / assert
        assert FakeReleaseFeed(latest_version="1.2.0").latest_version() == "1.2.0"

    def test_returns_none_by_default(self):
        # arrange / act / assert
        assert FakeReleaseFeed().latest_version() is None

    def test_raises_the_pinned_error(self):
        # arrange / act / assert
        with pytest.raises(RuntimeError, match="feed exploded"):
            FakeReleaseFeed(error=RuntimeError("feed exploded")).latest_version()

    def test_records_each_call(self):
        # arrange
        feed = FakeReleaseFeed()

        # act
        feed.latest_version()
        feed.latest_version()

        # assert
        assert feed.calls == 2
