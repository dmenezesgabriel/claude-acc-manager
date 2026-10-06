"""Unit tests for shared.claude_contract — the claude-version contract gate.

The supported band is pinned to measured claude releases: the full
credential contract cam interoperates with — ``wS()`` +
``.storage-write`` + ``.oauth_refresh.lock`` — exists together only from
claude 2.1.144; ``>=2.2.0`` is an unverified band and fails closed.
"""

import re
import subprocess
from pathlib import Path

import pytest

import claude_acc_manager.shared.claude_contract as claude_contract
from claude_acc_manager.shared.claude_contract import (
    CAM_ASSUME_CLAUDE_CONTRACT,
    VERSION_PROBE_TIMEOUT_S,
    ClaudeContract,
    UnsupportedClaudeVersionError,
    contract_for_version,
    probe_claude_contract,
    probe_claude_version,
)


class FakeSubprocessRun:
    """Named fake for subprocess.run — records kwargs, returns a canned banner."""

    def __init__(self, stdout: str) -> None:
        self._stdout = stdout
        self.calls: list[dict[str, object]] = []

    def __call__(self, args: list[str], **kwargs: object) -> "subprocess.CompletedProcess[str]":
        self.calls.append(dict(kwargs))
        return subprocess.CompletedProcess(args, 0, self._stdout, "")


def make_version_stub(tmp_path: Path, version: str, exit_code: int = 0) -> str:
    """Write a fake-claude script answering ``--version``."""
    stub = tmp_path / "fake-claude"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "if '--version' in sys.argv:\n"
        f"    print('{version} (Claude Code)'); sys.exit({exit_code})\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return str(stub)


def make_hanging_stub(tmp_path: Path) -> str:
    """A fake-claude whose --version sleeps forever."""
    stub = tmp_path / "fake-claude"
    stub.write_text(
        "#!/usr/bin/env python3\nimport time\ntime.sleep(30)\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return str(stub)


def refused_below(version: tuple[int, int, int]) -> ClaudeContract:
    """The exact contract a below-floor version must produce."""
    dotted = ".".join(map(str, version))
    return ClaudeContract(
        version=version,
        supported=False,
        assumed=False,
        reason=(
            f"claude {dotted} predates the credential contract cam "
            "interoperates with (introduced in 2.1.144) — upgrade claude"
        ),
    )


def refused_above(version: tuple[int, int, int]) -> ClaudeContract:
    """The exact contract a newer-than-verified version must produce."""
    dotted = ".".join(map(str, version))
    return ClaudeContract(
        version=version,
        supported=False,
        assumed=False,
        reason=(
            f"claude {dotted} is newer than cam's verified contract "
            "(verified through 2.1.144–2.1.x) — "
            "set CAM_ASSUME_CLAUDE_CONTRACT=1 to proceed anyway"
        ),
    )


def refused_undetermined(reason: str) -> ClaudeContract:
    """The exact contract an undeterminable version must produce."""
    return ClaudeContract(version=None, supported=False, assumed=False, reason=reason)


class TestContractForVersion:
    """contract_for_version maps a probed version onto the verified band."""

    @pytest.mark.parametrize(
        "version",
        [(0, 2, 126), (1, 0, 128), (2, 0, 77), (2, 1, 0), (2, 1, 100), (2, 1, 143)],
    )
    def test_below_the_floor_is_unsupported(self, version: tuple[int, int, int]) -> None:
        # arrange / act
        contract = contract_for_version(version)

        # assert — every pre-2.1.144 release lacks part of the credential
        # contract; the refusal names the version, the floor, and the remedy
        assert contract == refused_below(version)

    @pytest.mark.parametrize("version", [(2, 1, 144), (2, 1, 218), (2, 1, 288), (2, 1, 999)])
    def test_inside_the_band_is_supported(self, version: tuple[int, int, int]) -> None:
        # arrange / act
        contract = contract_for_version(version)

        # assert
        assert contract == ClaudeContract(
            version=version, supported=True, assumed=False, reason=None
        )

    @pytest.mark.parametrize("version", [(2, 2, 0), (2, 5, 40), (3, 0, 0), (9, 9, 9)])
    def test_above_the_verified_band_fails_closed(self, version: tuple[int, int, int]) -> None:
        # arrange / act
        contract = contract_for_version(version)

        # assert — the refusal names the override env var so a user on a
        # bleeding-edge claude knows the escape hatch
        assert contract == refused_above(version)

    def test_an_undetermined_version_is_unsupported(self) -> None:
        # arrange / act
        contract = contract_for_version(None)

        # assert — fail closed: nothing to check means nothing verified
        assert contract == refused_undetermined(
            "could not determine the claude version — "
            "set CAM_ASSUME_CLAUDE_CONTRACT=1 to proceed anyway"
        )


class TestRequireSupported:
    """require_supported raises the named refusal for out-of-band versions."""

    def test_supported_returns_none(self) -> None:
        # arrange
        contract = contract_for_version((2, 1, 288))

        # act / assert
        assert contract.require_supported() is None

    def test_unsupported_raises_naming_the_reason(self) -> None:
        # arrange
        contract = contract_for_version((2, 0, 77))

        # act / assert
        with pytest.raises(
            UnsupportedClaudeVersionError,
            match=re.escape(
                "claude 2.0.77 predates the credential contract cam "
                "interoperates with (introduced in 2.1.144) — upgrade claude"
            ),
        ):
            contract.require_supported()

    def test_the_refusal_is_a_value_error_for_dispatch_compatibility(self) -> None:
        # arrange / act / assert — dispatch already maps ValueError to `error:`
        assert issubclass(UnsupportedClaudeVersionError, ValueError)


class TestProbeClaudeVersion:
    """probe_claude_version runs ``<exe> --version`` and parses ``X.Y.Z``."""

    def test_parses_a_normal_banner(self, tmp_path: Path) -> None:
        # arrange
        stub = make_version_stub(tmp_path, "2.1.288")

        # act / assert
        assert probe_claude_version(stub) == (2, 1, 288)

    def test_the_probe_bounds_the_subprocess_wait(self, monkeypatch) -> None:
        # arrange — a dropped timeout kwarg would let a hung claude stall cam
        fake = FakeSubprocessRun("2.1.288 (Claude Code)")
        monkeypatch.setattr(claude_contract.subprocess, "run", fake)

        # act
        version = probe_claude_version("claude")

        # assert — the bounded wait is forwarded verbatim
        assert version == (2, 1, 288)
        assert fake.calls[0]["timeout"] == VERSION_PROBE_TIMEOUT_S

    def test_a_missing_binary_returns_none(self, tmp_path: Path) -> None:
        # arrange / act / assert — absent is not a probe *failure*
        assert probe_claude_version(str(tmp_path / "no-claude")) is None

    def test_a_nonzero_probe_raises_with_the_probe_output(self, tmp_path: Path) -> None:
        # arrange
        stub = make_version_stub(tmp_path, "2.1.288", exit_code=3)

        # act / assert — an undeterminable version must fail closed, carrying
        # whatever the probe printed (stderr, or stdout when stderr is empty)
        with pytest.raises(ValueError) as exc:
            probe_claude_version(stub)
        assert str(exc.value) == f"{stub} --version exited 3: 2.1.288 (Claude Code)"

    def test_an_unparseable_banner_raises(self, tmp_path: Path) -> None:
        # arrange
        stub = make_version_stub(tmp_path, "not-a-version")

        # act / assert
        with pytest.raises(ValueError, match="could not parse"):
            probe_claude_version(stub)

    def test_a_hanging_probe_times_out(self, tmp_path: Path) -> None:
        # arrange
        stub = make_hanging_stub(tmp_path)

        # act / assert
        with pytest.raises(ValueError, match="did not answer within"):
            probe_claude_version(stub, timeout_s=0.2)


class TestProbeClaudeContract:
    """probe_claude_contract resolves override + probe into one verdict."""

    def test_in_band_claude_is_supported(self, tmp_path: Path) -> None:
        # arrange
        stub = make_version_stub(tmp_path, "2.1.287")

        # act
        contract = probe_claude_contract({}, stub)

        # assert
        assert contract == ClaudeContract(
            version=(2, 1, 287), supported=True, assumed=False, reason=None
        )

    def test_out_of_band_claude_is_unsupported(self, tmp_path: Path) -> None:
        # arrange
        stub = make_version_stub(tmp_path, "2.0.77")

        # act
        contract = probe_claude_contract({}, stub)

        # assert
        assert contract == refused_below((2, 0, 77))

    def test_a_missing_binary_is_unsupported_not_a_crash(self, tmp_path: Path) -> None:
        # arrange / act
        contract = probe_claude_contract({}, str(tmp_path / "no-claude"))

        # assert
        assert contract == refused_undetermined(
            "could not determine the claude version — "
            "set CAM_ASSUME_CLAUDE_CONTRACT=1 to proceed anyway"
        )

    def test_an_unparseable_banner_is_unsupported(self, tmp_path: Path) -> None:
        # arrange
        stub = make_version_stub(tmp_path, "not-a-version")

        # act
        contract = probe_claude_contract({}, stub)

        # assert — the probe's failure becomes the refusal's reason
        assert contract == refused_undetermined(
            "could not parse claude version from 'not-a-version (Claude Code)\\n' "
            "— expected 'X.Y.Z (Claude Code)'"
        )

    def test_the_override_assumes_the_contract_regardless_of_version(self, tmp_path: Path) -> None:
        # arrange — the escape hatch for a claude newer than the verified band
        stub = make_version_stub(tmp_path, "9.9.9")
        env = {CAM_ASSUME_CLAUDE_CONTRACT: "1"}

        # act
        contract = probe_claude_contract(env, stub)

        # assert — the probed version is still recorded for diagnostics
        assert contract == ClaudeContract(
            version=(9, 9, 9), supported=True, assumed=True, reason=None
        )

    def test_the_override_covers_an_unprobeable_binary(self, tmp_path: Path) -> None:
        # arrange — claude absent/broken; the override takes responsibility
        env = {CAM_ASSUME_CLAUDE_CONTRACT: "1"}

        # act
        contract = probe_claude_contract(env, str(tmp_path / "no-claude"))

        # assert
        assert contract == ClaudeContract(version=None, supported=True, assumed=True, reason=None)

    def test_the_override_covers_a_failed_probe(self, tmp_path: Path) -> None:
        # arrange — an undeterminable version fails closed *unless* overridden
        stub = make_version_stub(tmp_path, "not-a-version")
        env = {CAM_ASSUME_CLAUDE_CONTRACT: "1"}

        # act
        contract = probe_claude_contract(env, stub)

        # assert
        assert contract == ClaudeContract(version=None, supported=True, assumed=True, reason=None)

    def test_an_empty_override_does_not_count(self, tmp_path: Path) -> None:
        # arrange — a defined-but-empty var is falsy, like the container probe
        stub = make_version_stub(tmp_path, "9.9.9")
        env = {CAM_ASSUME_CLAUDE_CONTRACT: ""}

        # act
        contract = probe_claude_contract(env, stub)

        # assert
        assert contract == refused_above((9, 9, 9))
