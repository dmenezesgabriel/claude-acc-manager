"""The claude-version contract gate: one version → one verdict.

cam interoperates with claude's credential write protocol — ``wS()`` path
resolution, ``.storage-write`` per-mutation locks, ``.oauth_refresh.lock`` —
and every piece of it is version-banded. Bisecting the linux-x64 npm bundles
showed the full contract exists together only from claude 2.1.144
(``.storage-write`` landed 2.1.136, ``CLAUDE_SECURESTORAGE_CONFIG_DIR``
2.1.144, ``.oauth_refresh.lock`` earlier); below that, sub-ranges each lack
a different subset, so partial support is impossible to state. Above 2.1.x
the contract is simply unverified — and band-internal drift already happened
once (the refresh lock's staleness moved 10s→60s mid-band).

So mutating/interoperating operations hold one rule: ``require_supported()``
inside ``[2.1.144, 2.2.0)``, else refuse. ``CAM_ASSUME_CLAUDE_CONTRACT``
(non-empty) marks the contract assumed and bypasses the check — the
deliberate escape hatch for a claude newer than the verified band.

Example:
    contract = probe_claude_contract(os.environ, "claude")
    contract.require_supported()  # raises UnsupportedClaudeVersionError
"""

import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass

# Evidence: linux-x64 bundle bisection — first release carrying wS() +
# .storage-write + .oauth_refresh.lock together is 2.1.144.
SUPPORTED_MIN = (2, 1, 144)
# First band whose contract is unverified. Bump only after re-verifying the
# bundle greps (the procedure lives in docs/adr/0015).
SUPPORTED_MAX_EXCLUSIVE = (2, 2, 0)

CAM_ASSUME_CLAUDE_CONTRACT = "CAM_ASSUME_CLAUDE_CONTRACT"
VERSION_PROBE_TIMEOUT_S = 15.0
_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


class UnsupportedClaudeVersionError(ValueError):
    """The installed claude is outside cam's verified contract band."""


@dataclass(frozen=True)
class ClaudeContract:
    """The verdict for one probed claude version.

    ``version`` is ``None`` when the probe could not determine one (absent
    binary, unparseable banner). ``assumed`` marks an override-bypassed
    contract — diagnostics should show it as assumed, not verified.

    Example:
        ClaudeContract((2, 1, 288), supported=True, assumed=False, reason=None)
    """

    version: tuple[int, int, int] | None
    supported: bool
    assumed: bool
    reason: str | None

    def require_supported(self) -> None:
        """Raise UnsupportedClaudeVersionError unless the contract is usable.

        Example:
            contract.require_supported()  # no-op on a verified 2.1.x
        """
        if not self.supported:
            raise UnsupportedClaudeVersionError(self.reason)


def _dotted(version: tuple[int, int, int]) -> str:
    """Render a version tuple the way ``claude --version`` prints it."""
    return ".".join(map(str, version))


def contract_for_version(version: tuple[int, int, int] | None) -> ClaudeContract:
    """Map a probed version onto the verified band — pure, no I/O.

    Example:
        contract_for_version((2, 1, 144)).supported  # True
    """
    if version is None:
        return ClaudeContract(
            version=None,
            supported=False,
            assumed=False,
            reason=(
                "could not determine the claude version — "
                f"set {CAM_ASSUME_CLAUDE_CONTRACT}=1 to proceed anyway"
            ),
        )
    dotted = _dotted(version)
    if version < SUPPORTED_MIN:
        return ClaudeContract(
            version=version,
            supported=False,
            assumed=False,
            reason=(
                f"claude {dotted} predates the credential contract cam "
                f"interoperates with (introduced in {_dotted(SUPPORTED_MIN)}) "
                "— upgrade claude"
            ),
        )
    if version >= SUPPORTED_MAX_EXCLUSIVE:
        return ClaudeContract(
            version=version,
            supported=False,
            assumed=False,
            reason=(
                f"claude {dotted} is newer than cam's verified contract "
                f"(verified through {_dotted(SUPPORTED_MIN)}–2.1.x) — "
                f"set {CAM_ASSUME_CLAUDE_CONTRACT}=1 to proceed anyway"
            ),
        )
    return ClaudeContract(version=version, supported=True, assumed=False, reason=None)


def probe_claude_version(
    executable: str, timeout_s: float = VERSION_PROBE_TIMEOUT_S
) -> tuple[int, int, int] | None:
    """Run ``<executable> --version`` → semver tuple; ``None`` when it can't run.

    Raises ValueError when the probe exits non-zero, hangs past *timeout_s*,
    or answers without a semver — an undeterminable version must fail closed.

    Example:
        probe_claude_version("claude")  # (2, 1, 288)
    """
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except OSError:
        return None
    except subprocess.TimeoutExpired:
        raise ValueError(f"{executable} --version did not answer within {timeout_s}s") from None
    if result.returncode != 0:
        raise ValueError(
            f"{executable} --version exited {result.returncode}: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    match = _VERSION_RE.search(result.stdout)
    if match is None:
        raise ValueError(
            f"could not parse claude version from {result.stdout!r} — "
            f"expected 'X.Y.Z (Claude Code)'"
        )
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def probe_claude_contract(env: Mapping[str, str], executable: str) -> ClaudeContract:
    """Resolve the contract: probe the binary, honor the override env var.

    A non-empty ``CAM_ASSUME_CLAUDE_CONTRACT`` marks the contract assumed —
    supported regardless of what the probe found (the version is still
    recorded for diagnostics when it can be). Otherwise the probed version
    goes through the band check, and a probe *failure* becomes an
    unsupported contract carrying the failure as its reason.

    Example:
        probe_claude_contract({"CAM_ASSUME_CLAUDE_CONTRACT": "1"}, "claude")
    """
    assumed = env.get(CAM_ASSUME_CLAUDE_CONTRACT)
    try:
        version = probe_claude_version(executable)
    except ValueError as exc:
        if assumed:
            return ClaudeContract(version=None, supported=True, assumed=True, reason=None)
        return ClaudeContract(version=None, supported=False, assumed=False, reason=str(exc))
    if assumed:
        return ClaudeContract(version=version, supported=True, assumed=True, reason=None)
    return contract_for_version(version)
