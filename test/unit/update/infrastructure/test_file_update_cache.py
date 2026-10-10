"""Unit tests for update.infrastructure.file_update_cache and the
UpdateCheckCachePort it implements."""

import json
from pathlib import Path

import pytest

from claude_acc_manager.update.application.ports import (
    UpdateCheckCachePort,
    UpdateCheckRecord,
)
from claude_acc_manager.update.infrastructure.file_update_cache import (
    FileUpdateCheckCache,
    _document_from_record,
)

_RECORD = UpdateCheckRecord(checked_at_s=1_760_000_000.0, latest_version="1.2.0")
_FAILED_CHECK = UpdateCheckRecord(checked_at_s=1_760_000_000.0, latest_version=None)


def make_cache(tmp_path: Path) -> FileUpdateCheckCache:
    return FileUpdateCheckCache(store_root=tmp_path / "store")


def cache_path(tmp_path: Path) -> Path:
    return tmp_path / "store" / "update-check.json"


def write_cache_file(tmp_path: Path, document: object) -> None:
    cache_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    cache_path(tmp_path).write_text(json.dumps(document), encoding="utf-8")


class TestCacheAdaptsThePort:
    def test_is_an_update_check_cache_port(self, tmp_path: Path):
        assert isinstance(make_cache(tmp_path), UpdateCheckCachePort)


class TestLoadNeverChecked:
    def test_returns_none_when_no_file_exists(self, tmp_path: Path):
        # arrange / act / assert
        assert make_cache(tmp_path).load() is None


class TestRoundTrip:
    def test_a_saved_record_is_returned_by_a_later_load(self, tmp_path: Path):
        # arrange
        cache = make_cache(tmp_path)

        # act
        cache.save(_RECORD)

        # assert
        assert cache.load() == _RECORD

    def test_a_cached_failure_is_not_confused_with_never_checked(self, tmp_path: Path):
        # A record with latest_version None (the check ran and failed) must
        # read back as a record — only an absent file means "fetch now".
        # arrange
        cache = make_cache(tmp_path)

        # act
        cache.save(_FAILED_CHECK)

        # assert
        assert cache.load() == _FAILED_CHECK

    def test_saving_again_replaces_the_record(self, tmp_path: Path):
        # arrange
        cache = make_cache(tmp_path)
        cache.save(_RECORD)

        # act
        cache.save(_FAILED_CHECK)

        # assert
        assert cache.load() == _FAILED_CHECK


class TestFileModes:
    def test_store_dir_and_cache_file_are_private(self, tmp_path: Path):
        # arrange / act
        make_cache(tmp_path).save(_RECORD)

        # assert
        assert (tmp_path / "store").stat().st_mode & 0o777 == 0o700
        assert cache_path(tmp_path).stat().st_mode & 0o777 == 0o600


class TestSharedLock:
    def test_save_uses_the_store_wide_lock_file(self, tmp_path: Path):
        # the same .lock FileAccountStore/FileUsageCache use (§3: one flock
        # governs every mutation this tool makes)
        # arrange / act
        make_cache(tmp_path).save(_RECORD)

        # assert
        assert (tmp_path / "store" / ".lock").exists()


class ValidationMessages:
    """Malformed update-check caches fail with exact, user-facing messages
    (every literal is pinned, mutation-tested — mirrors the usage cache's
    ValidationMessages matrix)."""

    @staticmethod
    def assert_message(tmp_path: Path, document: object, expected: str) -> None:
        # arrange
        write_cache_file(tmp_path, document)

        # act
        with pytest.raises(ValueError) as raised:
            make_cache(tmp_path).load()

        # assert
        assert str(raised.value) == expected


class TestTornDocument:
    def test_unparseable_json_fails_loudly(self, tmp_path: Path):
        # arrange — a torn file is never silently treated as absent (§8)
        cache_path(tmp_path).parent.mkdir(parents=True)
        cache_path(tmp_path).write_text("{not json", encoding="utf-8")

        # act
        with pytest.raises(ValueError) as raised:
            make_cache(tmp_path).load()

        # assert — fsio.read_json_object names the file; the parser detail varies
        assert str(raised.value).startswith(
            f"update-check file {cache_path(tmp_path)} is torn — could not be parsed:"
        )

    def test_a_non_object_document_fails_loudly(self, tmp_path: Path):
        # arrange / act / assert
        ValidationMessages.assert_message(
            tmp_path,
            [],
            f"update-check file {cache_path(tmp_path)} is list, not a JSON object",
        )


class TestDocumentValidationMessages(ValidationMessages):
    def test_unknown_top_level_field(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            {"schemaVersion": 1, "checked_at_s": 1.0, "latest_version": None, "x": 1},
            "update-check has unknown fields ['x']",
        )

    def test_missing_top_level_field(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            {"schemaVersion": 1, "checked_at_s": 1.0},
            "update-check is missing fields ['latest_version']",
        )

    def test_unsupported_schema_version(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            {"schemaVersion": 2, "checked_at_s": 1.0, "latest_version": None},
            "update-check schemaVersion 2 is not supported (expected 1)",
        )

    def test_boolean_schema_version_is_rejected(self, tmp_path: Path):
        # bool is a subclass of int (True == 1); a bare isinstance(int) check
        # alone would let it pass as schema version 1
        self.assert_message(
            tmp_path,
            {"schemaVersion": True, "checked_at_s": 1.0, "latest_version": None},
            "update-check schemaVersion True is not supported (expected 1)",
        )


class TestFieldValidationMessages(ValidationMessages):
    def test_checked_at_s_wrong_type(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            {"schemaVersion": 1, "checked_at_s": "soon", "latest_version": None},
            "update-check: checked_at_s must be a number, got 'soon'",
        )

    def test_checked_at_s_rejects_a_bool(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            {"schemaVersion": 1, "checked_at_s": True, "latest_version": None},
            "update-check: checked_at_s must be a number, got True",
        )

    def test_latest_version_wrong_type(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            {"schemaVersion": 1, "checked_at_s": 1.0, "latest_version": 42},
            "update-check: latest_version must be a str or null, got 42",
        )


class TestDocumentFromRecord:
    def test_serializes_the_schema_version_and_both_fields(self):
        # arrange / act
        document = _document_from_record(_RECORD)

        # assert
        assert document == {
            "schemaVersion": 1,
            "checked_at_s": 1_760_000_000.0,
            "latest_version": "1.2.0",
        }
