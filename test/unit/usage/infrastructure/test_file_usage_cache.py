"""Unit tests for usage.infrastructure.file_usage_cache and the
UsageCachePort it implements."""

import json
from pathlib import Path

import pytest

from claude_acc_manager.usage.application.ports import UsageCachePort
from claude_acc_manager.usage.domain.usage_cache_entry import (
    EMPTY_USAGE_CACHE_ENTRY,
    UsageCacheEntry,
)
from claude_acc_manager.usage.domain.usage_snapshot import ScopedWindow, UsageSnapshot, UsageWindow
from claude_acc_manager.usage.infrastructure.file_usage_cache import FileUsageCache, _entry_to_json

_FULL_SNAPSHOT = UsageSnapshot(
    five_hour=UsageWindow(pct=62.0, resets_at="2026-05-23T13:30:00Z"),
    seven_day=UsageWindow(pct=27.0, resets_at=None),
    scoped=(ScopedWindow(name="Fable", pct=84.0, resets_at="2026-05-27T13:00:00Z"),),
)

_FULL_ENTRY = UsageCacheEntry(
    last_good=_FULL_SNAPSHOT,
    fetched_at_s=1_700_000_000.0,
    consecutive_failures=2,
    last_error="http-429",
    backoff_until_s=1_700_000_300.0,
    last_429_at_s=1_700_000_000.0,
    next_poll_at_s=1_700_000_600.0,
    poll_interval_s=300.0,
)


def make_cache(tmp_path: Path) -> FileUsageCache:
    return FileUsageCache(store_root=tmp_path / "store")


def cache_doc(tmp_path: Path) -> dict[str, object]:
    text = (tmp_path / "store" / "usage-cache.json").read_text(encoding="utf-8")
    return json.loads(text)  # type: ignore[no-any-return]


def write_cache_file(tmp_path: Path, document: dict[str, object]) -> None:
    store_root = tmp_path / "store"
    store_root.mkdir(parents=True, exist_ok=True)
    (store_root / "usage-cache.json").write_text(json.dumps(document), encoding="utf-8")


class TestCacheAdaptsThePort:
    def test_is_a_usage_cache_port(self, tmp_path: Path):
        assert isinstance(make_cache(tmp_path), UsageCachePort)


class TestLoadUnknownAccount:
    def test_returns_the_empty_entry_when_no_file_exists(self, tmp_path: Path):
        assert make_cache(tmp_path).load("work") == EMPTY_USAGE_CACHE_ENTRY

    def test_returns_the_empty_entry_when_the_key_is_absent(self, tmp_path: Path):
        cache = make_cache(tmp_path)
        cache.save("work", _FULL_ENTRY)
        assert cache.load("personal") == EMPTY_USAGE_CACHE_ENTRY


class TestRoundTrip:
    def test_a_saved_entry_is_returned_by_a_later_load(self, tmp_path: Path):
        cache = make_cache(tmp_path)
        cache.save("work", _FULL_ENTRY)
        assert cache.load("work") == _FULL_ENTRY

    def test_the_empty_entry_round_trips(self, tmp_path: Path):
        cache = make_cache(tmp_path)
        cache.save("work", EMPTY_USAGE_CACHE_ENTRY)
        assert cache.load("work") == EMPTY_USAGE_CACHE_ENTRY

    def test_two_accounts_are_saved_independently(self, tmp_path: Path):
        cache = make_cache(tmp_path)
        cache.save("work", _FULL_ENTRY)
        cache.save("personal", EMPTY_USAGE_CACHE_ENTRY)
        assert cache.load("work") == _FULL_ENTRY
        assert cache.load("personal") == EMPTY_USAGE_CACHE_ENTRY

    def test_saving_again_does_not_disturb_other_accounts(self, tmp_path: Path):
        cache = make_cache(tmp_path)
        cache.save("work", _FULL_ENTRY)
        cache.save("personal", EMPTY_USAGE_CACHE_ENTRY)
        cache.save("work", EMPTY_USAGE_CACHE_ENTRY)
        assert cache.load("personal") == EMPTY_USAGE_CACHE_ENTRY


class TestFileModes:
    def test_store_dir_and_cache_file_are_private(self, tmp_path: Path):
        make_cache(tmp_path).save("work", EMPTY_USAGE_CACHE_ENTRY)
        assert (tmp_path / "store").stat().st_mode & 0o777 == 0o700
        assert (tmp_path / "store" / "usage-cache.json").stat().st_mode & 0o777 == 0o600


class TestSharedLock:
    def test_save_uses_the_store_wide_lock_file(self, tmp_path: Path):
        # the same .lock file FileAccountStore uses (plan §4.3: one flock
        # governs every mutation this tool makes)
        make_cache(tmp_path).save("work", EMPTY_USAGE_CACHE_ENTRY)
        assert (tmp_path / "store" / ".lock").exists()


class ValidationMessages:
    """Malformed usage caches fail with exact, user-facing messages (every
    literal is pinned, mutation-tested — mirrors accounts'
    file_account_store.py TestRegistryValidationMessages)."""

    @staticmethod
    def assert_message(tmp_path: Path, document: object, expected: str) -> None:
        # arrange
        write_cache_file(tmp_path, document)  # type: ignore[arg-type]

        # act
        with pytest.raises(ValueError) as raised:
            make_cache(tmp_path).load("work")

        # assert
        assert str(raised.value) == expected


class TestDocumentValidationMessages(ValidationMessages):
    def test_document_not_an_object(self, tmp_path: Path):
        self.assert_message(tmp_path, [], "usage cache must be a JSON object, got []")

    def test_unknown_top_level_field(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            {"schemaVersion": 1, "accounts": {}, "surprise": True},
            "usage cache has unknown fields ['surprise']",
        )

    def test_missing_top_level_field(self, tmp_path: Path):
        self.assert_message(
            tmp_path, {"schemaVersion": 1}, "usage cache is missing fields ['accounts']"
        )

    def test_unsupported_schema_version(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            {"schemaVersion": 2, "accounts": {}},
            "usage cache schemaVersion 2 is not supported (expected 1)",
        )

    def test_boolean_schema_version_is_rejected(self, tmp_path: Path):
        # bool is a subclass of int (True == 1); a bare isinstance(int) check
        # alone would let it pass as schema version 1
        self.assert_message(
            tmp_path,
            {"schemaVersion": True, "accounts": {}},
            "usage cache schemaVersion True is not supported (expected 1)",
        )

    def test_accounts_not_an_object(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            {"schemaVersion": 1, "accounts": []},
            "usage cache accounts must be a JSON object, got []",
        )


def _entry_dict(**overrides: object) -> dict[str, object]:
    # exercise the real serializer rather than hand-rolling a second shape
    record = _entry_to_json(_FULL_ENTRY)
    record.update(overrides)
    return record


def _document(**entry_overrides: object) -> dict[str, object]:
    return {"schemaVersion": 1, "accounts": {"work": _entry_dict(**entry_overrides)}}


class TestEntryValidationMessages(ValidationMessages):
    def test_entry_not_an_object(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            {"schemaVersion": 1, "accounts": {"work": "not-an-object"}},
            "usage cache entry 'work' must be a JSON object, got 'not-an-object'",
        )

    def test_unknown_field(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            _document(surprise=True),
            "usage cache entry 'work' has unknown fields ['surprise']",
        )

    def test_missing_field(self, tmp_path: Path):
        record = _entry_dict()
        del record["poll_interval_s"]
        self.assert_message(
            tmp_path,
            {"schemaVersion": 1, "accounts": {"work": record}},
            "usage cache entry 'work' is missing fields ['poll_interval_s']",
        )

    def test_fetched_at_s_wrong_type(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            _document(fetched_at_s="soon"),
            "usage cache entry 'work': fetched_at_s must be a number, got 'soon'",
        )

    def test_fetched_at_s_rejects_a_bool(self, tmp_path: Path):
        # bool is an int subclass — must not pass as a numeric timestamp
        self.assert_message(
            tmp_path,
            _document(fetched_at_s=True),
            "usage cache entry 'work': fetched_at_s must be a number, got True",
        )

    def test_consecutive_failures_wrong_type(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            _document(consecutive_failures="two"),
            "usage cache entry 'work': consecutive_failures must be an int, got 'two'",
        )

    def test_consecutive_failures_rejects_a_bool(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            _document(consecutive_failures=True),
            "usage cache entry 'work': consecutive_failures must be an int, got True",
        )

    def test_last_error_wrong_type(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            _document(last_error=42),
            "usage cache entry 'work': last_error must be a str or null, got 42",
        )

    def test_backoff_until_s_wrong_type(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            _document(backoff_until_s="soon"),
            "usage cache entry 'work': backoff_until_s must be a number, got 'soon'",
        )

    def test_last_429_at_s_wrong_type(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            _document(last_429_at_s="soon"),
            "usage cache entry 'work': last_429_at_s must be a number, got 'soon'",
        )

    def test_next_poll_at_s_wrong_type(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            _document(next_poll_at_s="soon"),
            "usage cache entry 'work': next_poll_at_s must be a number, got 'soon'",
        )

    def test_poll_interval_s_wrong_type(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            _document(poll_interval_s="soon"),
            "usage cache entry 'work': poll_interval_s must be a number, got 'soon'",
        )


class TestSnapshotValidationMessages(ValidationMessages):
    _CONTEXT = "usage cache entry 'work'.last_good"

    def test_not_an_object_or_null(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            _document(last_good="not-an-object"),
            f"{self._CONTEXT} must be a JSON object or null, got 'not-an-object'",
        )

    def test_unknown_field(self, tmp_path: Path):
        snapshot = _entry_to_json(_FULL_ENTRY)["last_good"]
        assert isinstance(snapshot, dict)
        snapshot["surprise"] = True
        self.assert_message(
            tmp_path,
            _document(last_good=snapshot),
            f"{self._CONTEXT} has unknown fields ['surprise']",
        )

    def test_missing_field(self, tmp_path: Path):
        snapshot = _entry_to_json(_FULL_ENTRY)["last_good"]
        assert isinstance(snapshot, dict)
        del snapshot["scoped"]
        self.assert_message(
            tmp_path, _document(last_good=snapshot), f"{self._CONTEXT} is missing fields ['scoped']"
        )


class TestWindowValidationMessages(ValidationMessages):
    _CONTEXT = "usage cache entry 'work'.last_good.five_hour"

    def _with_five_hour(self, five_hour: object) -> dict[str, object]:
        snapshot = _entry_to_json(_FULL_ENTRY)["last_good"]
        assert isinstance(snapshot, dict)
        snapshot["five_hour"] = five_hour
        return _document(last_good=snapshot)

    def test_not_an_object_or_null(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            self._with_five_hour("not-an-object"),
            f"{self._CONTEXT} must be a JSON object or null, got 'not-an-object'",
        )

    def test_unknown_field(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            self._with_five_hour({"pct": 1.0, "resets_at": None, "surprise": True}),
            f"{self._CONTEXT} has unknown fields ['surprise']",
        )

    def test_missing_field(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            self._with_five_hour({"pct": 1.0}),
            f"{self._CONTEXT} is missing fields ['resets_at']",
        )

    def test_pct_wrong_type(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            self._with_five_hour({"pct": "high", "resets_at": None}),
            f"{self._CONTEXT}: pct must be a number, got 'high'",
        )

    def test_pct_rejects_a_bool(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            self._with_five_hour({"pct": True, "resets_at": None}),
            f"{self._CONTEXT}: pct must be a number, got True",
        )

    def test_resets_at_wrong_type(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            self._with_five_hour({"pct": 1.0, "resets_at": 42}),
            f"{self._CONTEXT}: resets_at must be a str or null, got 42",
        )

    def test_seven_day_uses_its_own_context(self, tmp_path: Path):
        # pins that five_hour and seven_day are parsed with distinct context
        # strings, not one shared/hardcoded label
        snapshot = _entry_to_json(_FULL_ENTRY)["last_good"]
        assert isinstance(snapshot, dict)
        snapshot["seven_day"] = "not-an-object"
        self.assert_message(
            tmp_path,
            _document(last_good=snapshot),
            "usage cache entry 'work'.last_good.seven_day must be a JSON object or null, "
            "got 'not-an-object'",
        )


class TestScopedValidationMessages(ValidationMessages):
    _CONTEXT = "usage cache entry 'work'.last_good.scoped"

    def _with_scoped(self, scoped: object) -> dict[str, object]:
        snapshot = _entry_to_json(_FULL_ENTRY)["last_good"]
        assert isinstance(snapshot, dict)
        snapshot["scoped"] = scoped
        return _document(last_good=snapshot)

    def test_not_a_list(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            self._with_scoped("not-a-list"),
            f"{self._CONTEXT} must be a list, got 'not-a-list'",
        )

    def test_entry_not_an_object(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            self._with_scoped(["not-an-object"]),
            f"{self._CONTEXT}[0] must be a JSON object, got 'not-an-object'",
        )

    def test_entry_unknown_field(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            self._with_scoped([{"name": "Fable", "pct": 1.0, "resets_at": None, "surprise": True}]),
            f"{self._CONTEXT}[0] has unknown fields ['surprise']",
        )

    def test_entry_missing_field(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            self._with_scoped([{"name": "Fable", "pct": 1.0}]),
            f"{self._CONTEXT}[0] is missing fields ['resets_at']",
        )

    def test_name_wrong_type(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            self._with_scoped([{"name": 42, "pct": 1.0, "resets_at": None}]),
            f"{self._CONTEXT}[0]: name must be a str, got 42",
        )

    def test_pct_wrong_type(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            self._with_scoped([{"name": "Fable", "pct": "high", "resets_at": None}]),
            f"{self._CONTEXT}[0]: pct must be a number, got 'high'",
        )

    def test_pct_rejects_a_bool(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            self._with_scoped([{"name": "Fable", "pct": True, "resets_at": None}]),
            f"{self._CONTEXT}[0]: pct must be a number, got True",
        )

    def test_resets_at_wrong_type(self, tmp_path: Path):
        self.assert_message(
            tmp_path,
            self._with_scoped([{"name": "Fable", "pct": 1.0, "resets_at": 42}]),
            f"{self._CONTEXT}[0]: resets_at must be a str or null, got 42",
        )
