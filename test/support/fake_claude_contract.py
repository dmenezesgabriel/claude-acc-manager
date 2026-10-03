"""ClaudeContractPort fake returning a pinned contract verdict."""

from claude_acc_manager.accounts.application.ports import (
    ClaudeContractPort as AccountsClaudeContractPort,
)
from claude_acc_manager.shared.claude_contract import ClaudeContract
from claude_acc_manager.usage.application.ports import (
    ClaudeContractPort as UsageClaudeContractPort,
)


class FakeClaudeContractProbe(AccountsClaudeContractPort, UsageClaudeContractPort):
    """Returns the pinned contract and counts how often it was probed."""

    def __init__(self, contract: ClaudeContract) -> None:
        """Pin the verdict ``probe()`` returns."""
        self._contract = contract
        self.probes = 0

    def probe(self) -> ClaudeContract:
        """Count the probe and return the pinned verdict."""
        self.probes += 1
        return self._contract
