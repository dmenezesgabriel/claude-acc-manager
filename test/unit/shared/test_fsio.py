"""Unit tests for shared.fsio — atomic private-mode file writes.

The pinned contract: mkstemp in the target dir (0600 from creation, never
write-then-chmod), fsync of the temp file, then os.replace (ADR-0003).
"""

import json
import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from claude_acc_manager.shared import fsio


@contextmanager
def hostile_umask(mask: int) -> Iterator[None]:
    """Run a block under a process umask that would leak group/other bits."""
    previous = os.umask(mask)
    try:
        yield
    finally:
        os.umask(previous)


class ScriptedWrite:
    """Fake os.write: returns scripted byte counts, refuses empty chunks.

    Refusing empty chunks turns infinite-loop mutants into fast failures, and
    script exhaustion (IndexError) kills mutants that call os.write more often
    than the partial-write contract allows.
    """

    def __init__(self, returns: list[int]) -> None:
        self.returns = list(returns)
        self.chunks: list[bytes] = []

    def __call__(self, fd: int, data: bytes) -> int:
        if not data:
            raise OSError("empty chunk written")
        self.chunks.append(data)
        return self.returns.pop(0)


class CapturingMkstemp:
    """Fake tempfile.mkstemp: records kwargs, then delegates to the real one
    so the write flow continues to work against the real filesystem."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self._real = tempfile.mkstemp

    def __call__(self, **kwargs: object):
        self.calls.append(kwargs)
        return self._real(**kwargs)  # type: ignore[arg-type]


class FlakyReplace:
    """Fake os.replace that removes the temp file before failing — models a
    rename that consumed the tmp inode yet still surfaced an error, so a naive
    unlink in the cleanup path would raise FileNotFoundError and mask it."""

    def __init__(self, message: str) -> None:
        self.message = message

    def __call__(self, src: Path, dst: Path) -> None:
        src.unlink()
        raise OSError(self.message)


class ExplodingWrite:
    """Fake os.write that always fails — models a disk error mid-write."""

    def __call__(self, fd: int, data: bytes) -> int:
        raise OSError("disk gone")


def file_mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def dir_mode(path: Path) -> int:
    return file_mode(path)


def replace_only_this_path(target: Path, monkeypatch: pytest.MonkeyPatch, boom: str) -> None:
    """Route only *target* through FlakyReplace; other paths replace normally."""
    real = os.replace

    def selective(src: Path, dst: Path) -> None:
        if dst == target:
            FlakyReplace("boom")(src, dst)
        else:
            real(src, dst)

    monkeypatch.setattr(fsio.os, "replace", selective)


class TestAtomicWriteBytes:
    """Writes must be atomic (tmp+rename) and land with mode 0600 regardless
    of the process umask."""

    def test_creates_file_with_owner_only_mode_under_hostile_umask(self, tmp_path: Path):
        # arrange
        target = tmp_path / "registry.json"

        # act
        with hostile_umask(0o077):
            fsio.atomic_write_bytes(target, b"payload")

        # assert
        assert file_mode(target) == 0o600

    def test_owner_only_mode_even_when_umask_allows_everything(self, tmp_path: Path):
        # arrange — umask 000 must not leak group/other bits (mkstemp guarantee)
        target = tmp_path / "secrets.bin"

        # act
        with hostile_umask(0o000):
            fsio.atomic_write_bytes(target, b"secrets")

        # assert
        assert file_mode(target) == 0o600

    def test_writes_exact_payload(self, tmp_path: Path):
        # arrange
        target = tmp_path / "out.bin"

        # act
        fsio.atomic_write_bytes(target, b"\x00binary\xff")

        # assert
        assert target.read_bytes() == b"\x00binary\xff"

    def test_replaces_existing_content(self, tmp_path: Path):
        # arrange
        target = tmp_path / "state.json"
        target.write_bytes(b"old")

        # act
        fsio.atomic_write_bytes(target, b"new")

        # assert
        assert target.read_bytes() == b"new"

    def test_no_tmp_litter_in_target_directory(self, tmp_path: Path):
        # arrange
        target = tmp_path / "registry.json"

        # act
        fsio.atomic_write_bytes(target, b"payload")

        # assert — the only file in the dir is the target itself
        assert [p.name for p in tmp_path.iterdir()] == [target.name]

    def test_failed_write_leaves_previous_file_intact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # arrange — a broken write must not destroy or publish the old content
        target = tmp_path / "registry.json"
        fsio.atomic_write_bytes(target, b"good")
        monkeypatch.setattr(fsio.os, "write", ExplodingWrite())

        # act
        with pytest.raises(OSError):
            fsio.atomic_write_bytes(target, b"corrupted")

        # assert
        assert target.read_bytes() == b"good"

    def test_failed_write_cleans_up_tmp_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        # arrange
        target = tmp_path / "registry.json"
        monkeypatch.setattr(fsio.os, "write", ExplodingWrite())

        # act
        with pytest.raises(OSError):
            fsio.atomic_write_bytes(target, b"payload")

        # assert — no tmp files left behind
        assert [p.name for p in tmp_path.iterdir()] == []

    def test_creates_missing_parent_dir_private(self, tmp_path: Path):
        # arrange — deep target path, parent absent
        target = tmp_path / "accounts" / "work" / "registry.json"

        # act
        fsio.atomic_write_bytes(target, b"payload")

        # assert
        assert file_mode(target) == 0o600
        assert dir_mode(target.parent) == 0o700

    def test_temp_file_is_created_beside_target_same_filesystem(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # arrange — cross-device rename is not atomic (OSError EXDEV), so the
        # temp file must be created in the target's own directory
        capturer = CapturingMkstemp()
        monkeypatch.setattr(fsio.tempfile, "mkstemp", capturer)
        target = tmp_path / "nested" / "registry.json"

        # act
        fsio.atomic_write_bytes(target, b"payload")

        # assert
        assert capturer.calls == [{"dir": target.parent, "prefix": target.name, "suffix": ".tmp"}]

    def test_cleanup_failure_does_not_mask_the_original_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # arrange — the temp file vanishes during the failed replace; cleanup
        # must tolerate that and still surface the rename error itself
        target = tmp_path / "registry.json"
        fsio.atomic_write_bytes(target, b"good")
        replace_only_this_path(target, monkeypatch, boom="boom")

        # act
        with pytest.raises(OSError, match="boom"):
            fsio.atomic_write_bytes(target, b"corrupted")

        # assert
        assert target.read_bytes() == b"good"


class TestReadJsonObject:
    """Parsing must return the JSON object, or surface tears/shape loudly."""

    def test_returns_parsed_object(self, tmp_path: Path):
        # arrange
        target = tmp_path / "config.json"
        target.write_text('{"oauthAccount": {"emailAddress": "a@b.c"}}', encoding="utf-8")

        # act
        parsed = fsio.read_json_object(target, "config")

        # assert
        assert parsed["oauthAccount"]["emailAddress"] == "a@b.c"  # type: ignore[index]

    def test_raises_labeled_error_when_torn(self, tmp_path: Path):
        # arrange
        target = tmp_path / "config.json"
        target.write_text('{"oauthAccount": ', encoding="utf-8")

        # act / assert — the label pins which file failed (triage value)
        with pytest.raises(ValueError, match=r"config file .*torn"):
            fsio.read_json_object(target, "config")

    def test_raises_labeled_error_when_not_an_object(self, tmp_path: Path):
        # arrange
        target = tmp_path / "config.json"
        target.write_text("[1, 2]", encoding="utf-8")

        # act / assert — a JSON array is never a valid config object
        with pytest.raises(ValueError, match=r"config file .*list, not a JSON object"):
            fsio.read_json_object(target, "config")


class TestWriteAll:
    """os.write may accept fewer bytes than given — every byte must land."""

    def test_loops_over_partial_writes_until_exhausted(self, monkeypatch: pytest.MonkeyPatch):
        # arrange — first write accepts 2 bytes, second the remaining 3
        scripted = ScriptedWrite([2, 3])
        monkeypatch.setattr(fsio.os, "write", scripted)

        # act
        fsio._write_all(1, b"abcde")

        # assert — exactly the partial chunks, no extra call
        assert scripted.chunks == [b"abcde", b"cde"]

    def test_stops_after_the_last_byte(self, monkeypatch: pytest.MonkeyPatch):
        # arrange — a full write must not issue a trailing empty-chunk call
        scripted = ScriptedWrite([5])
        monkeypatch.setattr(fsio.os, "write", scripted)

        # act
        fsio._write_all(1, b"abcde")

        # assert
        assert scripted.chunks == [b"abcde"]


class TestAtomicWriteJson:
    """JSON payload written atomically and readable back."""

    def test_round_trips_payload(self, tmp_path: Path):
        # arrange
        target = tmp_path / "registry.json"
        payload = {"accounts": {"work": {"enabled": True}}, "active": None}

        # act
        fsio.atomic_write_json(target, payload)

        # assert
        assert json.loads(target.read_text(encoding="utf-8")) == payload

    def test_lands_with_private_mode(self, tmp_path: Path):
        # arrange
        target = tmp_path / "registry.json"

        # act
        with hostile_umask(0o000):
            fsio.atomic_write_json(target, {"k": "v"})

        # assert
        assert file_mode(target) == 0o600

    def test_writes_two_space_indented_json(self, tmp_path: Path):
        # arrange — the registry is read back by humans during incident triage
        target = tmp_path / "registry.json"

        # act
        fsio.atomic_write_json(target, {"active": None, "accounts": {}})

        # assert
        second_line = target.read_text(encoding="utf-8").splitlines()[1]
        assert second_line.startswith('  "active"')


class TestEnsurePrivateDir:
    """Directories must exist and be 0700 — enforced, not assumed."""

    def test_creates_nested_dir_owner_only(self, tmp_path: Path):
        # arrange
        target = tmp_path / "a" / "b" / "store"

        # act
        fsio.ensure_private_dir(target)

        # assert
        assert target.is_dir()
        assert dir_mode(target) == 0o700
        assert dir_mode(target.parent) == 0o700

    def test_leaves_existing_ancestor_dirs_untouched(self, tmp_path: Path):
        # arrange — a shared parent (e.g. ~/.local/share) that already exists
        # with a normal mode; only the missing leaf is ours to create + tighten
        shared = tmp_path / "share"
        shared.mkdir()
        os.chmod(shared, 0o755)
        target = shared / "claude-acc-manager"

        # act
        fsio.ensure_private_dir(target)

        # assert
        assert dir_mode(target) == 0o700
        assert dir_mode(shared) == 0o755  # the anchor above our tree is untouched

    def test_tightens_preexisting_loose_dir(self, tmp_path: Path):
        # arrange — a dir created earlier by something else, group/other-readable
        target = tmp_path / "store"
        target.mkdir()
        os.chmod(target, 0o755)

        # act
        fsio.ensure_private_dir(target)

        # assert
        assert dir_mode(target) == 0o700

    def test_tolerates_dir_appearing_between_check_and_mkdir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # arrange — a sibling process creates the dir after our exists() check;
        # mkdir must tolerate the race instead of crashing (exist_ok guard)
        target = tmp_path / "store"
        target.mkdir()
        real_exists = Path.exists

        def exists_denies_target(self: Path) -> bool:
            return False if self == target else real_exists(self)

        monkeypatch.setattr(Path, "exists", exists_denies_target)

        # act
        fsio.ensure_private_dir(target)

        # assert
        assert dir_mode(target) == 0o700
