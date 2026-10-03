"""Unit tests for usage.infrastructure.claude_contract_probe."""

from pathlib import Path

from claude_acc_manager.shared.claude_contract import (
    CAM_ASSUME_CLAUDE_CONTRACT,
)
from claude_acc_manager.usage.application.ports import ClaudeContractPort
from claude_acc_manager.usage.infrastructure.claude_contract_probe import (
    SubprocessClaudeContractProbe,
)


def make_version_stub(tmp_path: Path, version: str) -> str:
    """Write a fake-claude script answering ``--version``."""
    stub = tmp_path / "fake-claude"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "if '--version' in sys.argv:\n"
        f"    print('{version} (Claude Code)'); sys.exit(0)\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return str(stub)


class TestSubprocessClaudeContractProbeAdaptsThePort:
    """SubprocessClaudeContractProbe explicitly subclasses the port."""

    def test_is_a_claude_contract_port(self) -> None:
        # arrange / act / assert
        assert isinstance(SubprocessClaudeContractProbe(), ClaudeContractPort)

    def test_default_executable_is_path_resolved_claude(self) -> None:
        # arrange / act / assert
        assert SubprocessClaudeContractProbe()._executable == "claude"


class TestProbe:
    """probe() folds the binary's answer through the verified band."""

    def test_an_in_band_claude_probes_supported(self, tmp_path: Path) -> None:
        # arrange
        stub = make_version_stub(tmp_path, "2.1.288")

        # act
        contract = SubprocessClaudeContractProbe(executable=stub).probe()

        # assert
        assert contract.supported is True
        assert contract.version == (2, 1, 288)

    def test_the_override_env_var_is_read_at_probe_time(self, tmp_path: Path, monkeypatch) -> None:
        # arrange
        stub = make_version_stub(tmp_path, "9.9.9")
        monkeypatch.delenv(CAM_ASSUME_CLAUDE_CONTRACT, raising=False)

        # act
        before = SubprocessClaudeContractProbe(executable=stub).probe()
        monkeypatch.setenv(CAM_ASSUME_CLAUDE_CONTRACT, "1")
        after = SubprocessClaudeContractProbe(executable=stub).probe()

        # assert
        assert before.supported is False
        assert after.supported is True
