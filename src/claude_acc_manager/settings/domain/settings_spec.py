"""The ``autoswitch`` settings section — schema, clamps, and validation.

A dual discipline over one surface: ``SETTING_SPECS`` is the single source
of truth, so the forgiving clamp on load (hand-edited garbage degrades to
defaults, never crashes) and the strict parse on explicit user input
(``cam config set``, ``cam auto`` flags) can never drift apart. Unknown
keys are ignored here and preserved by the file adapter on write.

Example:
    spec = setting_spec("autoswitch.threshold")
    value = parse_setting_value(spec, "80")
"""

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, NamedTuple, cast

AutoStrategy = Literal["best", "next-available"]


class EffectiveSetting(NamedTuple):
    """One spec key's effective row: spec, value after clamps, explicitly set?"""

    spec: "SettingSpec"
    value: float | str
    is_set: bool


@dataclass(frozen=True)
class AutoSettings:
    """Policy knobs for the auto engine (``cam auto``).

    ``threshold`` is binding-window utilization (max of the 5h/7d
    percentages): at or above it the engine looks for a better account.
    ``hysteresis_pct`` is the margin a ``best`` candidate must beat the
    active account's headroom by, so near-line pairs cannot ping-pong.
    """

    threshold: float = 90.0
    interval_seconds: float = 60.0
    cooldown_seconds: float = 300.0
    hysteresis_pct: float = 10.0
    strategy: AutoStrategy = "best"


@dataclass(frozen=True)
class SettingSpec:
    """Metadata for one user-tunable ``settings.json`` key.

    ``section``/``json_key`` describe the file shape (``{"autoswitch":
    {"threshold": 80}}``); ``field`` is the snake_case ``AutoSettings``
    attribute. ``lo``/``hi`` bound ``float`` keys; ``choices`` bounds
    ``choice`` keys.
    """

    section: str
    json_key: str
    field: str
    kind: Literal["float", "choice"]
    lo: float | None = None
    hi: float | None = None
    choices: tuple[str, ...] = ()
    help: str = ""

    @property
    def dotted(self) -> str:
        """The ``cam config`` key spelling, e.g. ``autoswitch.threshold``."""
        return f"{self.section}.{self.json_key}"


SETTING_SPECS: dict[str, SettingSpec] = {
    spec.dotted: spec
    for spec in (
        SettingSpec(
            "autoswitch",
            "threshold",
            "threshold",
            "float",
            50.0,
            99.9,
            help="Switch when the binding 5h/7d window reaches this pct",
        ),
        SettingSpec(
            "autoswitch",
            "intervalSeconds",
            "interval_seconds",
            "float",
            15.0,
            3600.0,
            help="Poll interval for the cam auto loop, in seconds",
        ),
        SettingSpec(
            "autoswitch",
            "cooldownSeconds",
            "cooldown_seconds",
            "float",
            0.0,
            86400.0,
            help="Minimum seconds between proactive switches",
        ),
        SettingSpec(
            "autoswitch",
            "hysteresisPct",
            "hysteresis_pct",
            "float",
            0.0,
            50.0,
            help="A 'best' target must beat the active account by this many pct",
        ),
        SettingSpec(
            "autoswitch",
            "strategy",
            "strategy",
            "choice",
            choices=("best", "next-available"),
            help="How auto picks the target account",
        ),
    )
}


def clamped_auto_settings(section: Mapping[str, object]) -> AutoSettings:
    """Load the ``autoswitch`` section forgivingly: garbage degrades to defaults.

    Out-of-range numbers clamp into the spec bounds; wrong types (a bool is
    not a number) and unknown choices revert to the default; unknown keys are
    ignored. A bad hand edit can never break ``cam auto``.

    Example:
        clamped_auto_settings({"threshold": 80}).threshold == 80.0
    """
    # _clamped_choice returns a validated spec choice; the ternary narrows str
    # to the Literal — the only two strategies today.
    strategy_raw = _clamped_choice(SETTING_SPECS["autoswitch.strategy"], section.get("strategy"))
    strategy: AutoStrategy = "next-available" if strategy_raw == "next-available" else "best"
    return AutoSettings(
        threshold=_clamped_float(SETTING_SPECS["autoswitch.threshold"], section.get("threshold")),
        interval_seconds=_clamped_float(
            SETTING_SPECS["autoswitch.intervalSeconds"], section.get("intervalSeconds")
        ),
        cooldown_seconds=_clamped_float(
            SETTING_SPECS["autoswitch.cooldownSeconds"], section.get("cooldownSeconds")
        ),
        hysteresis_pct=_clamped_float(
            SETTING_SPECS["autoswitch.hysteresisPct"], section.get("hysteresisPct")
        ),
        strategy=strategy,
    )


def strict_override(settings: AutoSettings, overrides: Mapping[str, object]) -> AutoSettings:
    """Apply explicit (non-file) overrides with strict bounds, or ValueError.

    Unlike the forgiving file clamp, a value the user typed must fail loudly
    where it was given — the same rule ``cam config set`` enforces.

    Example:
        strict_override(AutoSettings(), {"threshold": 80.0}).threshold == 80.0
    """
    coerced: dict[str, object] = {}
    for field, value in overrides.items():
        spec = _spec_by_field(field)
        if spec.kind == "float":
            coerced[field] = _require_in_range(spec, value)
            continue
        if value not in spec.choices:
            raise ValueError(f"{spec.dotted} must be one of: {', '.join(spec.choices)}")
        coerced[field] = value
    return dataclasses.replace(settings, **coerced)


def setting_spec(dotted_key: str) -> SettingSpec:
    """Look up a spec by dotted key; unknown keys raise with the valid list.

    Example:
        setting_spec("autoswitch.threshold").field == "threshold"
    """
    spec = SETTING_SPECS.get(dotted_key)
    if spec is None:
        raise ValueError(f"unknown setting {dotted_key!r}\nValid keys: {', '.join(SETTING_SPECS)}")
    return spec


def parse_setting_value(spec: SettingSpec, raw_value: str) -> float | str:
    """Strictly parse a CLI-provided string for ``cam config set``.

    Out-of-range or mistyped values raise ``ValueError`` so the user learns
    about the problem when setting it, not as silently degraded behavior at
    ``cam auto`` time.
    """
    if spec.kind == "choice":
        if raw_value not in spec.choices:
            raise ValueError(f"{spec.dotted} must be one of: {', '.join(spec.choices)}")
        return raw_value
    try:
        value = float(raw_value)
    except ValueError:
        raise ValueError(f"{spec.dotted} expects a number, got {raw_value!r}") from None
    return _require_in_range(spec, value)


def format_setting_value(value: float | str) -> str:
    """Render a settings value the way ``settings.json`` writes it."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _clamped_float(spec: SettingSpec, raw: object) -> float:
    """*raw* coerced into spec bounds; wrong types revert to the spec default."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return cast("float", spec_default(spec))  # pragma: no mutate — cast() is a no-op
    assert spec.lo is not None and spec.hi is not None  # pragma: no mutate — spec invariant
    return float(min(max(raw, spec.lo), spec.hi))


def _clamped_choice(spec: SettingSpec, raw: object) -> str:
    """*raw* kept when it names a choice, else the spec default."""
    # `and`→`or` survives: the sole caller maps only "next-available" to a
    # non-default strategy, so keeping an invalid string is unobservable
    # (revisit if a third choice or a different consumer ever lands).
    if isinstance(raw, str) and raw in spec.choices:  # pragma: no mutate
        return raw
    return cast("str", spec_default(spec))  # pragma: no mutate — cast() is a no-op


def _require_in_range(spec: SettingSpec, value: object) -> float:
    """Strict numeric check for explicit user input (ValueError, not a clamp)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{spec.dotted} expects a number, got {value!r}")
    assert spec.lo is not None and spec.hi is not None  # pragma: no mutate — spec invariant
    if not spec.lo <= value <= spec.hi:
        raise ValueError(
            f"{spec.dotted} must be between {format_setting_value(spec.lo)} "
            f"and {format_setting_value(spec.hi)}, got {value!r}"
        )
    return float(value)


def _spec_by_field(field: str) -> SettingSpec:
    """The spec owning *field*; unknown fields raise with the valid list."""
    for spec in SETTING_SPECS.values():
        if spec.field == field:
            return spec
    raise ValueError(
        f"unknown setting field {field!r}; expected one of "
        f"{[spec.field for spec in SETTING_SPECS.values()]}"
    )


def spec_default(spec: SettingSpec) -> float | str:
    """The field's default read off the dataclass, so specs and class agree."""
    return getattr(AutoSettings(), spec.field)
