"""Unit tests for shared.container — container-runtime detection.

Probes: env vars, the .dockerenv marker, /proc/1/cgroup runtime names,
/proc/self/mountinfo mounts. Every probe anchors under an injected *fs_root*
so tests stay hermetic (docs/architecture.md §8.5).
"""

from pathlib import Path

import pytest

from claude_acc_manager.shared.container import running_in_container


class TestRunningInContainer:
    @pytest.mark.parametrize("var", ["CONTAINER", "container"])
    def test_a_container_env_var_marks_it(self, tmp_path: Path, var: str):
        # arrange / act / assert
        assert running_in_container({var: "podman"}, tmp_path) is True

    @pytest.mark.parametrize("var", ["CONTAINER", "container"])
    def test_an_empty_env_value_does_not_mark_it(self, tmp_path: Path, var: str):
        # arrange / act / assert — an unset-but-present empty var is falsy
        assert running_in_container({var: ""}, tmp_path) is False

    def test_the_dockerenv_marker_file_marks_it(self, tmp_path: Path):
        # arrange
        (tmp_path / ".dockerenv").touch()

        # act / assert
        assert running_in_container({}, tmp_path) is True

    @pytest.mark.parametrize("marker", ["docker", "lxc", "containerd", "kubepods"])
    def test_a_cgroup_runtime_name_marks_it(self, tmp_path: Path, marker: str):
        # arrange — /proc/1/cgroup naming the runtime (e.g. kubepods slices)
        cgroup = tmp_path / "proc" / "1"
        cgroup.mkdir(parents=True)
        (cgroup / "cgroup").write_text(f"0::/pod/runtime-{marker}/scope\n", encoding="utf-8")

        # act / assert
        assert running_in_container({}, tmp_path) is True

    def test_a_cgroup_without_runtime_names_does_not_mark_it(self, tmp_path: Path):
        # arrange — bare-metal cgroup v2 content
        cgroup = tmp_path / "proc" / "1"
        cgroup.mkdir(parents=True)
        (cgroup / "cgroup").write_text("0::/init.scope\n", encoding="utf-8")

        # act / assert
        assert running_in_container({}, tmp_path) is False

    @pytest.mark.parametrize("marker", ["docker", "overlay"])
    def test_a_mountinfo_signature_marks_it(self, tmp_path: Path, marker: str):
        # arrange — /proc/self/mountinfo carrying a container mount signature
        mountinfo = tmp_path / "proc" / "self"
        mountinfo.mkdir(parents=True)
        (mountinfo / "mountinfo").write_text(
            f"30 24 0:26 / / rw,relatime - {marker} {marker} rw\n", encoding="utf-8"
        )

        # act / assert
        assert running_in_container({}, tmp_path) is True

    def test_no_markers_anywhere_is_bare_metal(self, tmp_path: Path):
        # arrange — proc files exist but carry no container signature
        proc = tmp_path / "proc"
        (proc / "1").mkdir(parents=True)
        (proc / "self").mkdir()
        (proc / "1" / "cgroup").write_text("0::/init.scope\n", encoding="utf-8")
        (proc / "self" / "mountinfo").write_text(
            "30 24 8:1 / / rw,relatime - ext4 /dev/sda1 rw\n", encoding="utf-8"
        )

        # act / assert
        assert running_in_container({}, tmp_path) is False

    @pytest.mark.parametrize("path", ["proc/1/cgroup", "proc/self/mountinfo"])
    def test_an_unreadable_proc_file_is_skipped(self, tmp_path: Path, path: str):
        # arrange — the marked file exists but cannot be read (hardened host)
        target = tmp_path / path
        target.parent.mkdir(parents=True)
        target.write_text("docker\n", encoding="utf-8")
        target.chmod(0)

        # act / assert — the probe degrades to a pass, never a crash
        assert running_in_container({}, tmp_path) is False
        target.chmod(0o644)
