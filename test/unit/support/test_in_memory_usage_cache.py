"""Contract tests for the shared InMemoryUsageCache fake."""

from dataclasses import replace

from support.in_memory_usage_cache import InMemoryUsageCache

from claude_acc_manager.usage.application.ports import UsageCachePort
from claude_acc_manager.usage.domain.usage_cache_entry import EMPTY_USAGE_CACHE_ENTRY


class TestInMemoryUsageCacheAdaptsThePort:
    def test_is_a_usage_cache_port(self):
        assert isinstance(InMemoryUsageCache(), UsageCachePort)


class TestLoad:
    def test_an_unknown_account_loads_the_empty_entry(self):
        assert InMemoryUsageCache().load("work") == EMPTY_USAGE_CACHE_ENTRY


class TestSave:
    def test_a_saved_entry_is_returned_by_a_later_load(self):
        # arrange
        cache = InMemoryUsageCache()
        entry = replace(EMPTY_USAGE_CACHE_ENTRY, consecutive_failures=2)

        # act
        cache.save("work", entry)

        # assert
        assert cache.load("work") == entry

    def test_entries_are_keyed_independently_per_account(self):
        # arrange
        cache = InMemoryUsageCache()
        work_entry = replace(EMPTY_USAGE_CACHE_ENTRY, consecutive_failures=1)

        # act
        cache.save("work", work_entry)

        # assert — a different account is untouched
        assert cache.load("personal") == EMPTY_USAGE_CACHE_ENTRY
