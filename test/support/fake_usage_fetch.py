"""UsageFetchPort fake that replays canned UsageReports per account."""

from claude_acc_manager.usage.application.ports import UsageFetchPort
from claude_acc_manager.usage.domain.usage_report import UsageReport


class FakeUsageFetch(UsageFetchPort):
    """Returns the canned report for each account; records every call.

    An account with no canned report yields a snapshot=None "unknown"
    report — the state a never-fetched row is in. ``calls`` records
    ``(account_key, is_active, force, threshold)`` per invocation.
    """

    def __init__(self, reports: dict[str, UsageReport] | None = None) -> None:
        """Pin per-account reports keyed by account name."""
        self._reports = reports or {}
        self.calls: list[tuple[str, bool, bool, float | None]] = []

    def execute(
        self,
        account_key: str,
        is_active: bool,
        *,
        force: bool,
        threshold: float | None,
    ) -> UsageReport:
        """Record the call, then replay the canned report (or "unknown")."""
        self.calls.append((account_key, is_active, force, threshold))
        return self._reports.get(
            account_key,
            UsageReport(None, stale=False, last_error=None, permanent_auth_error=False),
        )
