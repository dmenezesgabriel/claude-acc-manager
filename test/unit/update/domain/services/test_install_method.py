"""install_method — prefix pairs, env overrides, registry-vs-source receipts."""

import json
from pathlib import PurePosixPath

import pytest

from claude_acc_manager.update.domain.services.install_method import (
    InstallMethod,
    detect_install_method,
    upgrade_argv,
)

_UV_PREFIX = PurePosixPath("/home/u/.local/share/uv/tools/claude-acc-manager")
_PIPX_PREFIX = PurePosixPath("/home/u/.local/share/pipx/venvs/claude-acc-manager")


def _uv_receipt(requirement: str) -> str:
    return f"[tool]\nrequirements = [{requirement}]\n"


def _pipx_metadata(package_or_url: object) -> str:
    return json.dumps(
        {"main_package": {"package": "claude-acc-manager", "package_or_url": package_or_url}}
    )


_UV_REGISTRY = _uv_receipt('{ name = "claude-acc-manager", specifier = "==1.1.0" }')
_PIPX_REGISTRY = _pipx_metadata("claude-acc-manager")


class TestPrefixPairs:
    @pytest.mark.parametrize(
        ("prefix", "receipt", "expected"),
        [
            (_UV_PREFIX, _UV_REGISTRY, InstallMethod.UV),
            (_PIPX_PREFIX, _PIPX_REGISTRY, InstallMethod.PIPX),
            (PurePosixPath("/home/u/project/.venv"), _UV_REGISTRY, InstallMethod.UNKNOWN),
            (PurePosixPath("/usr"), None, InstallMethod.UNKNOWN),
            (
                PurePosixPath("/opt/tools/uv/claude-acc-manager"),
                _UV_REGISTRY,
                InstallMethod.UNKNOWN,
            ),
        ],
    )
    def test_the_prefix_names_the_manager(
        self, prefix: PurePosixPath, receipt: str | None, expected: InstallMethod
    ) -> None:
        # Arrange
        env: dict[str, str] = {}

        # Act
        method = detect_install_method(prefix, env, receipt)

        # Assert
        assert method is expected


class TestEnvOverride:
    @pytest.mark.parametrize(
        ("variable", "receipt", "expected"),
        [
            ("UV_TOOL_DIR", _UV_REGISTRY, InstallMethod.UV),
            ("PIPX_HOME", _PIPX_REGISTRY, InstallMethod.PIPX),
        ],
    )
    def test_a_relocated_root_counts_when_the_prefix_is_under_it(
        self, variable: str, receipt: str, expected: InstallMethod
    ) -> None:
        # Arrange
        prefix = PurePosixPath("/opt/tools/claude-acc-manager")

        # Act
        method = detect_install_method(prefix, {variable: "/opt/tools"}, receipt)

        # Assert
        assert method is expected

    @pytest.mark.parametrize("variable", ["UV_TOOL_DIR", "PIPX_HOME"])
    def test_a_root_the_prefix_is_not_under_is_ignored(self, variable: str) -> None:
        prefix = PurePosixPath("/home/u/project/.venv")

        assert detect_install_method(prefix, {variable: "/opt/tools"}, _UV_REGISTRY) is (
            InstallMethod.UNKNOWN
        )

    def test_an_empty_root_is_ignored(self) -> None:
        prefix = PurePosixPath("/home/u/project/.venv")

        assert detect_install_method(prefix, {"UV_TOOL_DIR": ""}, _UV_REGISTRY) is (
            InstallMethod.UNKNOWN
        )


class TestUvReceipt:
    @pytest.mark.parametrize(
        "requirement",
        [
            '{ name = "claude-acc-manager", specifier = "==1.1.0" }',
            '{ name = "claude-acc-manager" }',
            '{ name = "claude-acc-manager", index = "https://pypi.org/simple" }',
            # Our entry need not come first, e.g. after a `--with` extra.
            '{ name = "rich" }, { name = "claude-acc-manager" }',
        ],
    )
    def test_a_registry_requirement_is_uv(self, requirement: str) -> None:
        assert detect_install_method(_UV_PREFIX, {}, _uv_receipt(requirement)) is InstallMethod.UV

    @pytest.mark.parametrize(
        "source",
        [
            'git = "https://github.com/o/claude-acc-manager"',
            'url = "https://example.org/claude_acc_manager-1.1.0.tar.gz"',
            'path = "/home/u/claude_acc_manager-1.1.0-py3-none-any.whl"',
            'directory = "/home/u/claude-acc-manager"',
            'editable = "/home/u/claude-acc-manager"',
            'virtual = "/home/u/claude-acc-manager"',
        ],
    )
    def test_a_source_requirement_is_vcs(self, source: str) -> None:
        receipt = _uv_receipt(f'{{ name = "claude-acc-manager", {source} }}')

        assert detect_install_method(_UV_PREFIX, {}, receipt) is InstallMethod.VCS

    @pytest.mark.parametrize(
        "receipt",
        [
            None,
            "not = [toml",
            "[tool]\n",
            "tool = 1\n",
            "[tool]\nrequirements = 1\n",
            _uv_receipt('{ name = "other-tool" }'),
            _uv_receipt('"claude-acc-manager"'),
        ],
    )
    def test_a_missing_or_unreadable_receipt_is_unknown(self, receipt: str | None) -> None:
        assert detect_install_method(_UV_PREFIX, {}, receipt) is InstallMethod.UNKNOWN


class TestPipxMetadata:
    @pytest.mark.parametrize(
        "package_or_url",
        ["claude-acc-manager", "claude-acc-manager==1.1.0", "claude-acc-manager[tui]>=1.0"],
    )
    def test_a_registry_spec_is_pipx(self, package_or_url: str) -> None:
        metadata = _pipx_metadata(package_or_url)

        assert detect_install_method(_PIPX_PREFIX, {}, metadata) is InstallMethod.PIPX

    @pytest.mark.parametrize(
        "package_or_url",
        [
            "claude-acc-manager @ git+https://github.com/o/claude-acc-manager",
            "git+https://github.com/o/claude-acc-manager",
            "/home/u/claude-acc-manager",
            "claude-acc-manager-fork",
        ],
    )
    def test_a_source_spec_is_vcs(self, package_or_url: str) -> None:
        metadata = _pipx_metadata(package_or_url)

        assert detect_install_method(_PIPX_PREFIX, {}, metadata) is InstallMethod.VCS

    @pytest.mark.parametrize(
        "metadata",
        [None, "{not json", "[]", '{"main_package": 1}', _pipx_metadata(None)],
    )
    def test_a_missing_or_unreadable_metadata_is_unknown(self, metadata: str | None) -> None:
        assert detect_install_method(_PIPX_PREFIX, {}, metadata) is InstallMethod.UNKNOWN


class TestUpgradeArgv:
    """The delegated upgrade argv per method; None where delegation can't apply it.

    uv accepts a ``name==version`` specifier on `tool upgrade` (verified
    2026-10-10, `uv tool upgrade --help`); `pipx upgrade` takes the bare
    name only, so a pinned upgrade is not delegable under pipx. VCS and
    UNKNOWN installs are never delegated — a git receipt would re-resolve
    the ref, and an unknown install may be a source checkout too.
    """

    @pytest.mark.parametrize("target", [None, "1.2.0"])
    def test_a_uv_install_upgrades_through_uv_tool(self, target: str | None) -> None:
        # Act
        argv = upgrade_argv(InstallMethod.UV, target)

        # Assert — the bare name takes latest; a pin rides the == specifier
        assert argv == [
            "uv",
            "tool",
            "upgrade",
            "claude-acc-manager" if target is None else f"claude-acc-manager=={target}",
        ]

    def test_a_pipx_install_upgrades_through_pipx(self) -> None:
        # Act / Assert
        assert upgrade_argv(InstallMethod.PIPX) == [
            "pipx",
            "upgrade",
            "claude-acc-manager",
        ]

    @pytest.mark.parametrize(
        ("method", "target"),
        [
            (InstallMethod.PIPX, "1.2.0"),
            (InstallMethod.VCS, None),
            (InstallMethod.VCS, "1.2.0"),
            (InstallMethod.UNKNOWN, None),
            (InstallMethod.UNKNOWN, "1.2.0"),
        ],
    )
    def test_an_undelegable_install_returns_no_argv(
        self, method: InstallMethod, target: str | None
    ) -> None:
        # Act / Assert
        assert upgrade_argv(method, target) is None
