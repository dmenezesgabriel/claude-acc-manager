"""Assemble the ``cam doctor`` report from probed facts.

The port returns raw observations; this use case owns the verdicts —
which variables are worth showing, when a missing store is a warning,
what an unsupported contract reads as. ``cam_version`` is injected (the
composition root resolves it) so application code never reaches for
``importlib.metadata``.
"""

from collections.abc import Mapping

from claude_acc_manager.accounts.application.doctor_report import (
    DiagnosticsFacts,
    DoctorCheck,
    DoctorReport,
    DoctorSection,
    DoctorStatus,
    LockObservation,
)
from claude_acc_manager.accounts.application.ports import DiagnosticsPort
from claude_acc_manager.shared.claude_contract import (
    CAM_ASSUME_CLAUDE_CONTRACT,
    SUPPORTED_MAX_EXCLUSIVE,
    SUPPORTED_MIN,
    ClaudeContract,
)

# Env vars the report surfaces, in display order — the ones that steer
# cam's own resolution plus the contract bypass (a warn when set).
_ENV_VARS = (
    "CLAUDE_CONFIG_DIR",
    "CLAUDE_SECURESTORAGE_CONFIG_DIR",
    "XDG_DATA_HOME",
    CAM_ASSUME_CLAUDE_CONTRACT,
)

_TERMINAL_VARS = ("TERM", "COLORTERM", "NO_COLOR")


def _presence(present: bool) -> str:
    """The parenthetical a path row ends on."""
    return "(present)" if present else "(absent)"


def _tty(tty: bool) -> str:
    """How a stream row reads."""
    return "tty" if tty else "not a tty"


class CollectDoctorReport:
    """Build a ``DoctorReport`` from one probe snapshot.

    Example:
        report = CollectDoctorReport(probe, cam_version="1.2.3").execute()
    """

    def __init__(self, diagnostics: DiagnosticsPort, *, cam_version: str) -> None:
        """Inject the probe and the resolved package version."""
        self._diagnostics = diagnostics
        self._cam_version = cam_version

    def execute(self) -> DoctorReport:
        """Return every section in fixed display order (cam → system)."""
        facts = self._diagnostics.probe()
        return DoctorReport(
            sections=(
                self._cam(facts),
                self._contract(facts.contract),
                self._paths(facts),
                self._locks(facts.locks),
                self._environment(facts.env),
                self._terminal(facts),
                self._system(facts),
            )
        )

    def _cam(self, facts: DiagnosticsFacts) -> DoctorSection:
        """Cam's own version and store health."""
        missing = "" if facts.store_exists else " (missing)"
        return DoctorSection(
            title="cam",
            checks=(
                DoctorCheck("version", self._cam_version, "info"),
                DoctorCheck(
                    "store",
                    f"{facts.store_root}{missing}",
                    "ok" if facts.store_exists else "warn",
                ),
            ),
        )

    @staticmethod
    def _contract(contract: ClaudeContract) -> DoctorSection:
        """The claude version and its band verdict — the interop gate."""
        version = (
            ".".join(map(str, contract.version)) if contract.version is not None else "not found"
        )
        band_min = ".".join(map(str, SUPPORTED_MIN))
        band_max = ".".join(map(str, SUPPORTED_MAX_EXCLUSIVE))
        band = f"{band_min}–{band_max} (exclusive)"
        if contract.assumed:
            status: DoctorStatus = "warn"
            value = f"assumed via {CAM_ASSUME_CLAUDE_CONTRACT} (verified band {band})"
        elif contract.supported:
            status = "ok"
            value = f"supported — verified band {band}"
        else:
            status = "fail"
            value = contract.reason or "unsupported"
        return DoctorSection(
            title="claude contract",
            checks=(
                DoctorCheck("claude --version", version, "info"),
                DoctorCheck("contract", value, status),
            ),
        )

    @staticmethod
    def _paths(facts: DiagnosticsFacts) -> DoctorSection:
        """The live-slot files and the accounts dir, with presence."""
        return DoctorSection(
            title="paths",
            checks=(
                DoctorCheck(
                    "credentials",
                    f"{facts.credentials_path} {_presence(facts.credentials_present)}",
                    "info",
                ),
                DoctorCheck(
                    "config",
                    f"{facts.config_path} {_presence(facts.config_present)}",
                    "info",
                ),
                DoctorCheck(
                    "accounts dir",
                    f"{facts.accounts_dir} {_presence(facts.accounts_dir_exists)}",
                    "info",
                ),
            ),
        )

    @staticmethod
    def _locks(locks: tuple[LockObservation, ...]) -> DoctorSection:
        """Every coordination lock's state — held/stale both warn."""
        return DoctorSection(
            title="locks",
            checks=tuple(
                DoctorCheck(
                    lock.name,
                    f"{lock.state} ({lock.path})",
                    "ok" if lock.state == "free" else "warn",
                )
                for lock in locks
            ),
        )

    @staticmethod
    def _environment(env: Mapping[str, str]) -> DoctorSection:
        """The env vars that steer cam; the contract bypass warns when set."""
        return DoctorSection(
            title="environment",
            checks=tuple(
                DoctorCheck(
                    name,
                    env.get(name, "unset"),
                    "warn" if name == CAM_ASSUME_CLAUDE_CONTRACT and env.get(name) else "info",
                )
                for name in _ENV_VARS
            ),
        )

    @staticmethod
    def _terminal(facts: DiagnosticsFacts) -> DoctorSection:
        """Stream/terminal facts — what the styling layer sees."""
        return DoctorSection(
            title="terminal",
            checks=(
                DoctorCheck("stdin", _tty(facts.stdin_tty), "info"),
                DoctorCheck("stdout", _tty(facts.stdout_tty), "info"),
                DoctorCheck("interactive", "yes" if facts.interactive else "no", "info"),
                *(
                    DoctorCheck(name, facts.env.get(name, "unset"), "info")
                    for name in _TERMINAL_VARS
                ),
            ),
        )

    @staticmethod
    def _system(facts: DiagnosticsFacts) -> DoctorSection:
        """Python, platform, and privilege facts."""
        return DoctorSection(
            title="system",
            checks=(
                DoctorCheck("python", facts.python, "info"),
                DoctorCheck("platform", facts.platform, "info"),
                DoctorCheck("euid", str(facts.euid), "info"),
                DoctorCheck("container", "yes" if facts.in_container else "no", "info"),
            ),
        )
