"""FileSettings — SettingsPort over an atomic 0600 ``settings.json``.

Reads are forgiving (the file is user-editable: a torn write degrades to
defaults rather than crash ``cam auto``); writes are strict — a file too
broken to read-modify-write raises instead of silently discarding the user's
other keys. Unknown keys and sections are preserved on write so a newer
``cam`` never eats an older one's settings.

Example:
    settings = FileSettings(store_root).load()
"""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from claude_acc_manager.settings.application.ports import SettingsPort
from claude_acc_manager.settings.domain.settings_spec import (
    SETTING_SPECS,
    AutoSettings,
    EffectiveSetting,
    SettingSpec,
    clamped_auto_settings,
)
from claude_acc_manager.shared import fsio
from claude_acc_manager.shared.file_lock import exclusive_file_lock

_SCHEMA_VERSION = 1


def _section_from(document: Mapping[str, object], section: str) -> Mapping[str, object]:
    """The named section of *document* as a mapping; garbage reads as empty."""
    raw = document.get(section)
    if not isinstance(raw, Mapping):
        return {}
    return cast("Mapping[str, object]", raw)  # pragma: no mutate — cast() is a no-op


def _read_forgiving(path: Path) -> Mapping[str, object]:
    """The file as a mapping for *load* — torn/non-object reads as empty."""
    if not path.exists():
        return {}
    try:
        document: object = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return {}
    if not isinstance(document, dict):
        return {}
    return cast("Mapping[str, object]", document)  # pragma: no mutate — cast() is a no-op


def _read_for_write(path: Path) -> dict[str, object]:
    """The file as a mutable dict for read-modify-write — strict, unlike load."""
    if not path.exists():
        return {"schemaVersion": _SCHEMA_VERSION}
    try:
        document: object = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path} is not valid JSON ({exc}); fix or delete it first") from exc
    if not isinstance(document, dict):
        raise ValueError(
            f"{path} is not a JSON object (got {type(document).__name__}); fix or delete it first"
        )
    return cast("dict[str, object]", document)  # pragma: no mutate — cast() is a no-op


def _writable_section(document: dict[str, object], section: str) -> dict[str, object]:
    """The section dict inside *document* to mutate; replaced when garbage."""
    raw = document.get(section)
    if isinstance(raw, dict):
        return cast("dict[str, object]", raw)  # pragma: no mutate — cast() is a no-op
    section_map: dict[str, object] = {}
    document[section] = section_map
    return section_map


class FileSettings(SettingsPort):
    """SettingsPort over ``settings.json`` under the store's shared ``.lock``.

    Example:
        FileSettings(store_root).set_value(setting_spec("autoswitch.threshold"), 80.0)
    """

    def __init__(self, store_root: Path) -> None:
        """Store at *store_root*: settings.json + the shared .lock live there."""
        self._path = store_root / "settings.json"
        self._lock_path = store_root / ".lock"

    @property
    def path(self) -> Path:
        """The settings file path (``cam config path``)."""
        return self._path

    def load(self) -> AutoSettings:
        """Forgiving load (port contract): missing/corrupt file → defaults."""
        section = _section_from(_read_forgiving(self._path), "autoswitch")
        return clamped_auto_settings(section)

    def set_value(self, spec: SettingSpec, value: float | str) -> None:
        """Persist *value* under *spec*'s key, preserving unknown keys (port contract)."""
        fsio.ensure_private_dir(self._path.parent)
        with exclusive_file_lock(self._lock_path):
            document = _read_for_write(self._path)
            _writable_section(document, spec.section)[spec.json_key] = value
            fsio.atomic_write_json(self._path, document)

    def unset_value(self, spec: SettingSpec) -> bool:
        """Remove *spec*'s key under the lock (port contract); empty sections drop."""
        fsio.ensure_private_dir(self._path.parent)
        with exclusive_file_lock(self._lock_path):
            document = _read_for_write(self._path)
            section = document.get(spec.section)
            if not isinstance(section, dict) or spec.json_key not in section:
                return False
            del section[spec.json_key]
            if not section:
                del document[spec.section]
            fsio.atomic_write_json(self._path, document)
            return True

    def effective(self) -> tuple[EffectiveSetting, ...]:
        """One row per spec key (port contract); ``is_set`` mirrors file presence."""
        raw_section = _section_from(_read_forgiving(self._path), "autoswitch")
        settings = clamped_auto_settings(raw_section)
        return tuple(
            EffectiveSetting(
                spec=spec,
                value=getattr(settings, spec.field),
                is_set=spec.json_key in raw_section,
            )
            for spec in SETTING_SPECS.values()
        )
