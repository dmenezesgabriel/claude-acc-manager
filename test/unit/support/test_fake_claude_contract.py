"""Unit tests for the FakeClaudeContractProbe support fake."""

from claude_acc_manager.accounts.application.ports import (
    ClaudeContractPort as AccountsClaudeContractPort,
)
from claude_acc_manager.shared.claude_contract import ClaudeContract
from claude_acc_manager.usage.application.ports import (
    ClaudeContractPort as UsageClaudeContractPort,
)
from test.support.fake_claude_contract import FakeClaudeContractProbe


class TestFakeClaudeContractProbe:
    """The fake satisfies both components' ports and reports what callers probed."""

    def test_is_a_claude_contract_port(self) -> None:
        # arrange / act / assert — one pinned verdict serves both components
        contract = ClaudeContract(version=(2, 1, 288), supported=True, assumed=False, reason=None)
        probe = FakeClaudeContractProbe(contract)
        assert isinstance(probe, AccountsClaudeContractPort)
        assert isinstance(probe, UsageClaudeContractPort)

    def test_probe_returns_the_pinned_contract_and_counts(self) -> None:
        # arrange
        contract = ClaudeContract(
            version=None, supported=False, assumed=False, reason="stubbed refusal"
        )
        probe = FakeClaudeContractProbe(contract)

        # act
        first = probe.probe()
        second = probe.probe()

        # assert
        assert first is contract
        assert second is contract
        assert probe.probes == 2
