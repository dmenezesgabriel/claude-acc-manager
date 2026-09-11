"""In-memory UsageCachePort fake for hermetic use-case tests."""

from claude_acc_manager.usage.application.ports import UsageCachePort
from claude_acc_manager.usage.domain.usage_cache_entry import (
    EMPTY_USAGE_CACHE_ENTRY,
    UsageCacheEntry,
)


class InMemoryUsageCache(UsageCachePort):
    """UsageCachePort backed by a dict keyed on account name string."""

    def __init__(self) -> None:
        """Start with no cached entries."""
        self._entries: dict[str, UsageCacheEntry] = {}

    def load(self, account_key: str) -> UsageCacheEntry:
        """The account's cached entry, or EMPTY_USAGE_CACHE_ENTRY when unknown."""
        return self._entries.get(account_key, EMPTY_USAGE_CACHE_ENTRY)

    def save(self, account_key: str, entry: UsageCacheEntry) -> None:
        """Replace the account's cached entry."""
        self._entries[account_key] = entry
