"""Natural-language preference extraction with deterministic and optional LLM paths."""

from __future__ import annotations

import json
import re
from typing import Any

import requests

from homelens.config import Settings
from homelens.schemas import DEFAULT_WEIGHTS, IntentParseResult


HDB_TOWNS = (
    "ANG MO KIO",
    "BEDOK",
    "BISHAN",
    "BUKIT BATOK",
    "BUKIT MERAH",
    "BUKIT PANJANG",
    "BUKIT TIMAH",
    "CENTRAL AREA",
    "CHOA CHU KANG",
    "CLEMENTI",
    "GEYLANG",
    "HOUGANG",
    "JURONG EAST",
    "JURONG WEST",
    "KALLANG/WHAMPOA",
    "MARINE PARADE",
    "PASIR RIS",
    "PUNGGOL",
    "QUEENSTOWN",
    "SEMBAWANG",
    "SENGKANG",
    "SERANGOON",
    "TAMPINES",
    "TOA PAYOH",
    "WOODLANDS",
    "YISHUN",
)

TOWN_ALIASES = {
    "宏茂桥": "ANG MO KIO",
    "勿洛": "BEDOK",
    "碧山": "BISHAN",
    "武吉巴督": "BUKIT BATOK",
    "红山": "BUKIT MERAH",
    "武吉班让": "BUKIT PANJANG",
    "武吉知马": "BUKIT TIMAH",
    "中央区": "CENTRAL AREA",
    "蔡厝港": "CHOA CHU KANG",
    "金文泰": "CLEMENTI",
    "芽笼": "GEYLANG",
    "后港": "HOUGANG",
    "裕廊东": "JURONG EAST",
    "裕廊西": "JURONG WEST",
    "加冷": "KALLANG/WHAMPOA",
    "黄埔": "KALLANG/WHAMPOA",
    "马林百列": "MARINE PARADE",
    "巴西立": "PASIR RIS",
    "榜鹅": "PUNGGOL",
    "女皇镇": "QUEENSTOWN",
    "三巴旺": "SEMBAWANG",
    "盛港": "SENGKANG",
    "实龙岗": "SERANGOON",
    "淡滨尼": "TAMPINES",
    "大巴窑": "TOA PAYOH",
    "兀兰": "WOODLANDS",
    "义顺": "YISHUN",
}


def _number_with_suffix(number: str, suffix: str | None) -> float:
    value = float(number.replace(",", ""))
    suffix = (suffix or "").lower()
    if suffix == "k":
        return value * 1_000
    if suffix == "m":
        return value * 1_000_000
    if suffix == "万":
        return value * 10_000
    return value


def _priority_weights(text: str) -> dict[str, float] | None:
    lower = text.lower()
    weights = dict(DEFAULT_WEIGHTS)
    changed = False
    keyword_map = {
        "affordability": ("cheap", "affordable", "low price", "budget", "便宜", "性价比"),
        "space": ("spacious", "large", "bigger", "more space", "宽敞", "面积", "大一点"),
        "lease": ("long lease", "newer flat", "remaining lease", "屋龄", "剩余租期", "新一点"),
        "location": ("preferably in", "preferred town", "location", "区域", "地区", "最好在"),
        "transit": ("mrt", "metro", "train", "bus", "commute", "地铁", "巴士", "通勤"),
        "amenities": ("park", "hawker", "amenities", "school", "公园", "食阁", "学校", "环境"),
    }
    for dimension, keywords in keyword_map.items():
        if any(keyword in lower for keyword in keywords):
            weights[dimension] *= 1.8
            changed = True
    return weights if changed else None


def _location_reference(text: str) -> tuple[str | None, float | None]:
    """Conservatively extract a named place and optional radius from common phrasing."""

    generic = {"mrt", "metro", "station", "地铁", "地铁站", "学校", "公园", "商场"}

    def clean(value: str) -> str | None:
        phrase = value.strip(" ,，.;；。")
        phrase = re.sub(r"^(?:the|a|an|在|住在|想住在|靠近|临近)\s*", "", phrase, flags=re.I)
        phrase = re.split(
            r"\s+(?:under|below|with|and|budget|max(?:imum)?)\b|(?:预算|房型|以内)",
            phrase,
            maxsplit=1,
            flags=re.I,
        )[0].strip()
        if not 2 <= len(phrase) <= 100 or phrase.casefold() in generic:
            return None
        return phrase

    patterns = (
        (
            r"(?:within|under|less than|no more than)\s*([\d.]+)\s*(km|m)\s*"
            r"(?:of|from)\s+([^,.;，。；]{2,100})",
            "distance_first",
        ),
        (
            r"(?:离|距离)\s*([^,.;，。；]{2,80}?)\s*(?:不超过|少于|在)?\s*"
            r"([\d.]+)\s*(公里|千米|km|米|m)(?:以内|之内)?",
            "place_first",
        ),
        (
            r"(?:^|[,，;；])\s*(?:在|住在|想住在)?\s*([^,.;，。；]{2,80}?)\s*"
            r"(?:附近|周边)\s*([\d.]+)?\s*(公里|千米|km|米|m)?",
            "place_first_optional",
        ),
    )
    for pattern, order in patterns:
        match = re.search(pattern, text, flags=re.I)
        if not match:
            continue
        if order == "distance_first":
            distance, unit, raw_place = match.group(1), match.group(2), match.group(3)
        else:
            raw_place, distance, unit = match.group(1), match.group(2), match.group(3)
        place = clean(raw_place)
        metres = None
        if distance:
            metres = float(distance) * (1_000 if str(unit).lower() in {"km", "公里", "千米"} else 1)
        if place:
            return place, metres

    near = re.search(r"(?:near|close to|around)\s+([^,.;，。；]{2,100})", text, flags=re.I)
    if near:
        return clean(near.group(1)), None
    chinese_near = re.search(r"(?:靠近|临近)\s*([^,.;，。；]{2,100})", text, flags=re.I)
    if chinese_near:
        return clean(chinese_near.group(1)), None
    return None, None


def parse_with_rules(text: str) -> IntentParseResult:
    values: dict[str, Any] = {}
    warnings: list[str] = []
    lower = text.lower().strip()
    if not lower:
        return IntentParseResult(values={}, method="rules")

    budget_patterns = (
        r"(?:budget(?:\s+is|\s+of)?|under|below|less than|up to|max(?:imum)?|预算|不超过|低于|以内)"
        r"\s*(?:s\$|\$|sgd)?\s*([\d,.]+)\s*(k|m|万)?",
        r"(?:s\$|\$|sgd)\s*([\d,.]+)\s*(k|m)?",
        r"([\d,.]+)\s*(万)\s*(?:预算|以内|以下)?",
    )
    for pattern in budget_patterns:
        match = re.search(pattern, lower, flags=re.IGNORECASE)
        if match:
            values["budget"] = _number_with_suffix(match.group(1), match.group(2))
            break

    flat_types: list[str] = []
    for number in range(1, 6):
        if re.search(rf"\b{number}\s*[- ]?(?:room|bedroom)s?\b", lower) or re.search(
            rf"{number}\s*房(?:式)?", text
        ):
            flat_types.append(f"{number} ROOM")
    chinese_flat_types = {
        "一房": "1 ROOM",
        "两房": "2 ROOM",
        "二房": "2 ROOM",
        "三房": "3 ROOM",
        "四房": "4 ROOM",
        "五房": "5 ROOM",
    }
    for phrase, flat_type in chinese_flat_types.items():
        if phrase in text:
            flat_types.append(flat_type)
    if "executive" in lower:
        flat_types.append("EXECUTIVE")
    if "multi-generation" in lower or "multigeneration" in lower:
        flat_types.append("MULTI-GENERATION")
    if flat_types:
        values["flat_types"] = list(dict.fromkeys(flat_types))

    towns: list[str] = []
    negated_towns: list[str] = []
    matched_town_phrases: list[str] = []
    town_phrases = {town.lower(): town for town in HDB_TOWNS}
    town_phrases.update({alias.lower(): town for alias, town in TOWN_ALIASES.items()})
    for phrase, town in sorted(town_phrases.items(), key=lambda item: len(item[0]), reverse=True):
        for match in re.finditer(re.escape(phrase), lower):
            prefix = lower[max(0, match.start() - 24) : match.start()]
            if re.search(
                r"(?:not\s+(?:in|at|want)?|do\s+not\s+want|don't\s+want|avoid|"
                r"不要|不想要|避开|不考虑)\s*$",
                prefix,
            ):
                negated_towns.append(town)
            else:
                towns.append(town)
                matched_town_phrases.append(phrase)
    towns = list(dict.fromkeys(towns))
    if towns:
        values["preferred_towns"] = towns
        strict_town_pattern = "|".join(
            sorted((re.escape(phrase) for phrase in matched_town_phrases), key=len, reverse=True)
        )
        if re.search(
            rf"(?:only\s+(?:in|at)|must\s+be\s+(?:in|at)|只要|仅限)\s*(?:区)?\s*(?:{strict_town_pattern})",
            lower,
        ):
            values["require_preferred_town"] = True
    if negated_towns:
        warnings.append(
            "Excluded-town language was recognised but exclusion ranking is not yet supported: "
            + ", ".join(dict.fromkeys(negated_towns))
            + "."
        )

    area_match = re.search(
        r"(?:at least|min(?:imum)?|不少于|至少)\s*([\d.]+)\s*(?:sqm|m2|m²|平)", lower
    )
    if area_match:
        values["min_floor_area_sqm"] = float(area_match.group(1))

    lease_match = re.search(
        r"(?:at least|min(?:imum)?|不少于|至少)\s*([\d.]+)\s*(?:years?|年)"
        r"(?:\s+(?:remaining|lease|租期))?",
        lower,
    )
    if lease_match and any(keyword in lower for keyword in ("lease", "remaining", "租期")):
        values["min_remaining_lease_years"] = float(lease_match.group(1))

    mrt_match = re.search(
        r"(?:within|under|less than|不超过|以内)\s*([\d.]+)\s*(km|m|公里|米)"
        r".{0,20}(?:mrt|metro|station|地铁)",
        lower,
    )
    if mrt_match:
        distance = float(mrt_match.group(1))
        if mrt_match.group(2) in ("km", "公里"):
            distance *= 1_000
        values["max_mrt_distance_m"] = distance

    location_query, anchor_distance = _location_reference(text)
    if location_query:
        values["location_query"] = location_query
    if anchor_distance is not None:
        values["max_anchor_distance_m"] = anchor_distance

    weights = _priority_weights(text)
    if weights:
        values["weights"] = weights
    if text and not values:
        warnings.append("No structured preference was recognised; use the form fields for precision.")
    return IntentParseResult(values=values, method="rules", warnings=tuple(warnings))


class OpenAIIntentParser:
    """Use Responses API structured output only when a key is configured."""

    def __init__(self, settings: Settings, timeout_seconds: int = 45) -> None:
        self.settings = settings
        self.timeout_seconds = timeout_seconds

    @property
    def available(self) -> bool:
        return bool(
            self.settings.enable_llm
            and self.settings.openai_api_key
            and self.settings.openai_base_url
            and self.settings.openai_model
        )

    @property
    def endpoint(self) -> str:
        return f"{self.settings.openai_base_url}/responses"

    @staticmethod
    def _schema() -> dict[str, Any]:
        nullable_number = {"anyOf": [{"type": "number"}, {"type": "null"}]}
        return {
            "type": "object",
            "properties": {
                "budget": nullable_number,
                "flat_types": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "1 ROOM",
                            "2 ROOM",
                            "3 ROOM",
                            "4 ROOM",
                            "5 ROOM",
                            "EXECUTIVE",
                            "MULTI-GENERATION",
                        ],
                    },
                },
                "preferred_towns": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(HDB_TOWNS)},
                },
                "min_floor_area_sqm": nullable_number,
                "min_remaining_lease_years": nullable_number,
                "max_mrt_distance_m": nullable_number,
                "location_query": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "max_anchor_distance_m": nullable_number,
                "require_preferred_town": {"type": "boolean"},
                "priorities": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "affordability",
                            "space",
                            "lease",
                            "location",
                            "transit",
                            "amenities",
                            "market_activity",
                        ],
                    },
                },
            },
            "required": [
                "budget",
                "flat_types",
                "preferred_towns",
                "min_floor_area_sqm",
                "min_remaining_lease_years",
                "max_mrt_distance_m",
                "location_query",
                "max_anchor_distance_m",
                "require_preferred_town",
                "priorities",
            ],
            "additionalProperties": False,
        }

    @staticmethod
    def _extract_text(response: dict[str, Any]) -> str:
        if isinstance(response.get("output_text"), str):
            return response["output_text"]
        for item in response.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    return content["text"]
        raise ValueError("OpenAI response did not contain output text")

    def parse(self, text: str) -> IntentParseResult:
        if not self.available:
            raise RuntimeError("OpenAI intent parsing is not configured")
        payload = {
            "model": self.settings.openai_model,
            "instructions": (
                "Extract Singapore HDB resale preferences only. Do not invent housing facts, "
                "prices, distances, or coordinates. Put a named landmark, address, school, "
                "workplace or POI in location_query exactly as the user described it; a backend "
                "geocoder will resolve it. Use null or empty arrays when unspecified."
            ),
            "input": text,
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "housing_preferences",
                    "strict": True,
                    "schema": self._schema(),
                }
            },
        }
        response = requests.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        values = json.loads(self._extract_text(response.json()))
        priorities = values.pop("priorities", [])
        values = {key: value for key, value in values.items() if value not in (None, [], "")}
        if priorities:
            weights = dict(DEFAULT_WEIGHTS)
            for priority in priorities:
                weights[priority] *= 1.8
            values["weights"] = weights
        return IntentParseResult(values=values, method="openai")


def parse_intent(text: str, settings: Settings | None = None, use_llm: bool = False) -> IntentParseResult:
    rule_result = parse_with_rules(text)
    if not use_llm:
        return rule_result
    current_settings = settings or Settings.from_environment()
    parser = OpenAIIntentParser(current_settings)
    if not parser.available:
        return IntentParseResult(
            values=rule_result.values,
            method="rules",
            warnings=rule_result.warnings
            + ("OpenAI was requested but is not configured; deterministic rules were used.",),
        )
    try:
        return parser.parse(text)
    except (requests.RequestException, ValueError, json.JSONDecodeError) as error:
        return IntentParseResult(
            values=rule_result.values,
            method="rules_fallback",
            warnings=rule_result.warnings
            + (f"OpenAI parsing failed; deterministic rules were used ({type(error).__name__}).",),
        )
