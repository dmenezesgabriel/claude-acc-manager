"""Unit tests for the FakeClaudeContractProbe support fake."""

from claude_acc_manager.accounts.application.ports import ClaudeContractPort
from claude_acc_manager.shared.claude_contract import ClaudeContract
from test.support.fake_claude_contract import FakeClaudeContractProbe


class TestFakeClaudeContractProbe:
    """The fake satisfies the port and reports what callers probed."""

    def test_is_a_claude_contract_port(self) -> None:
        # arrange / act / assert
        contract = ClaudeContract(version=(2, 1, 288), supported=True, assumed=False, reason=None)
        assert isinstance(FakeClaudeContractProbe(contract), ClaudeContractPort)

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
