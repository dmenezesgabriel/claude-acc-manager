"""ClaudeContractPort adapter probing ``<exe> --version`` via subprocess.

The verdict logic lives in ``shared.claude_contract``; this adapter is the
thin I/O boundary that binds the ambient environment and executable name.

Example:
    contract = SubprocessClaudeContractProbe().probe()
    contract.require_supported()
"""

import os

from claude_acc_manager.accounts.application.ports import ClaudeContractPort
from claude_acc_manager.shared.claude_contract import (
    ClaudeContract,
    probe_claude_contract,
)


class SubprocessClaudeContractProbe(ClaudeContractPort):
    """Run ``claude --version`` and fold the answer through the band check.

    Example:
        probe = SubprocessClaudeContractProbe()
        probe.probe().require_supported()
    """

    def __init__(self, executable: str = "claude") -> None:
        """Name the binary to probe (injectable for hermetic stub-binary tests)."""
        self._executable = executable

    def probe(self) -> ClaudeContract:
        """Resolve the contract; honors CAM_ASSUME_CLAUDE_CONTRACT in os.environ.

        The environment is read at probe time so a long-running process sees
        the ambient value on every call, not a startup snapshot.
        """
        return probe_claude_contract(os.environ, self._executable)
