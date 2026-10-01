"""FetchAccountUsage that raises KeyboardInterrupt — Ctrl-C landing mid-fetch."""

from claude_acc_manager.usage.application.use_cases.fetch_account_usage import (
    FetchAccountUsage,
    UsageReport,
)


class InterruptingFetchUsage(FetchAccountUsage):
    """Simulates Ctrl-C inside a use case; no ports are ever touched."""

    def __init__(self) -> None:
        """Execute raises before it can read a port — inject nothing."""

    def execute(self, account_key: str, is_active: bool) -> UsageReport:
        """Raise KeyboardInterrupt unconditionally."""
        raise KeyboardInterrupt
