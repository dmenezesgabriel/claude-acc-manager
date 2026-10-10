"""Contract tests for the shared InMemoryUpdateCheckCache fake."""

from support.in_memory_update_cache import InMemoryUpdateCheckCache

from claude_acc_manager.update.application.ports import (
    UpdateCheckCachePort,
    UpdateCheckRecord,
)

_RECORD = UpdateCheckRecord(checked_at_s=1.0, latest_version="1.2.0")
_LATER_FAILED = UpdateCheckRecord(checked_at_s=2.0, latest_version=None)


class TestInMemoryUpdateCheckCacheAdaptsThePort:
    def test_is_an_update_check_cache_port(self):
        assert isinstance(InMemoryUpdateCheckCache(), UpdateCheckCachePort)


class TestLoad:
    def test_returns_none_when_nothing_was_stored(self):
        # arrange / act / assert
        assert InMemoryUpdateCheckCache().load() is None

    def test_returns_the_seeded_record(self):
        # arrange / act / assert
        assert InMemoryUpdateCheckCache(_RECORD).load() == _RECORD


class TestSave:
    def test_a_saved_record_is_returned_by_a_later_load(self):
        # arrange
        cache = InMemoryUpdateCheckCache()

        # act
        cache.save(_RECORD)

        # assert
        assert cache.load() == _RECORD

    def test_records_each_save_in_order(self):
        # arrange
        cache = InMemoryUpdateCheckCache()

        # act
        cache.save(_RECORD)
        cache.save(_LATER_FAILED)

        # assert
        assert cache.saves == [_RECORD, _LATER_FAILED]
