"""Validated data structures shared by CLI, API and recommendation code."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any


ALLOWED_FLAT_TYPES = (
    "1 ROOM",
    "2 ROOM",
    "3 ROOM",
    "4 ROOM",
    "5 ROOM",
    "EXECUTIVE",
    "MULTI-GENERATION",
)

DEFAULT_WEIGHTS = {
    "affordability": 0.32,
    "space": 0.18,
    "lease": 0.13,
    "location": 0.15,
    "transit": 0.12,
    "amenities": 0.06,
    "market_activity": 0.04,
}


def _normalise_string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        raise ValueError("text selections must be a string or a list of strings")
    if any(not isinstance(item, str) for item in value):
        raise ValueError("text selections must contain strings only")
    return tuple(dict.fromkeys(item.strip().upper() for item in value if item.strip()))


@dataclass
class UserPreferences:
    budget: float
    flat_types: tuple[str, ...] = ()
    preferred_towns: tuple[str, ...] = ()
    min_floor_area_sqm: float | None = None
    min_remaining_lease_years: float | None = None
    max_mrt_distance_m: float | None = None
    require_preferred_town: bool = False
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))

    def __post_init__(self) -> None:
        if isinstance(self.budget, bool):
            raise ValueError("budget must be a finite number greater than zero")
        self.budget = float(self.budget)
        if not math.isfinite(self.budget) or self.budget <= 0:
            raise ValueError("budget must be a finite number greater than zero")

        self.flat_types = _normalise_string_tuple(self.flat_types)
        invalid = set(self.flat_types) - set(ALLOWED_FLAT_TYPES)
        if invalid:
            raise ValueError(f"unsupported flat type(s): {', '.join(sorted(invalid))}")
        self.preferred_towns = _normalise_string_tuple(self.preferred_towns)

        for attribute in (
            "min_floor_area_sqm",
            "min_remaining_lease_years",
            "max_mrt_distance_m",
        ):
            value = getattr(self, attribute)
            if value is not None:
                if isinstance(value, bool):
                    raise ValueError(f"{attribute} must be a finite non-negative number")
                value = float(value)
                if not math.isfinite(value) or value < 0:
                    raise ValueError(f"{attribute} must be a finite non-negative number")
                setattr(self, attribute, value)

        if not isinstance(self.require_preferred_town, bool):
            raise ValueError("require_preferred_town must be true or false")

        if not isinstance(self.weights, dict):
            raise ValueError("weights must be an object containing numeric values")
        unknown_weights = set(self.weights) - set(DEFAULT_WEIGHTS)
        if unknown_weights:
            raise ValueError(
                "unsupported recommendation weight(s): "
                + ", ".join(sorted(unknown_weights))
            )
        clean_weights: dict[str, float] = {}
        for name, default in DEFAULT_WEIGHTS.items():
            raw_value = self.weights.get(name, default)
            if isinstance(raw_value, bool):
                raise ValueError(f"weight {name} must be a finite non-negative number")
            value = float(raw_value)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"weight {name} must be a finite non-negative number")
            clean_weights[name] = value
        if sum(clean_weights.values()) <= 0:
            raise ValueError("at least one recommendation weight must be positive")
        self.weights = clean_weights

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "UserPreferences":
        allowed = {
            "budget",
            "flat_types",
            "preferred_towns",
            "min_floor_area_sqm",
            "min_remaining_lease_years",
            "max_mrt_distance_m",
            "require_preferred_town",
            "weights",
        }
        data = {key: value for key, value in payload.items() if key in allowed}
        if "budget" not in data or data["budget"] in (None, ""):
            raise ValueError("budget is required")
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["flat_types"] = list(self.flat_types)
        result["preferred_towns"] = list(self.preferred_towns)
        return result


@dataclass(frozen=True)
class IntentParseResult:
    values: dict[str, Any]
    method: str
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"values": self.values, "method": self.method, "warnings": list(self.warnings)}
