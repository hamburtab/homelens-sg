"""General-purpose, data-grounded Singapore housing agent.

This module intentionally lives beside, rather than inside, ``advisor.py``.  The
legacy advisor remains available for comparison while this agent follows a
plan -> local tools -> answer loop without requiring a complete housing profile.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import re
import threading
import time
from typing import Any, TYPE_CHECKING
from uuid import uuid4

import numpy as np
import pandas as pd
import requests

from homelens.config import PROJECT_ROOT, Settings
from homelens.errors import DataUnavailableError
from homelens.geospatial import haversine_matrix
from homelens.intent import HDB_TOWNS, TOWN_ALIASES, parse_with_rules
from homelens.recommender import recommend
from homelens.schemas import ALLOWED_FLAT_TYPES, UserPreferences

if TYPE_CHECKING:
    from homelens.service import HomeLensService


PLAN_INTENTS = {
    "help",
    "market_overview",
    "recommendation",
    "listing_search",
    "area_analysis",
    "area_compare",
    "historical_price",
    "current_information",
    "general_housing",
}
HOUSING_MODES = {"rent", "buy", "both", "unknown"}
RENTAL_SCOPES = {"room", "whole_unit", "any"}
SORT_OPTIONS = {
    "default",
    "price_asc",
    "price_desc",
    "floor_area_desc",
    "mrt_distance_asc",
    "newest",
}
REFINEMENT_TYPES = {
    "none",
    "new_search",
    "more_options",
    "explain_current",
}
PRIORITIES = {
    "affordability",
    "space",
    "lease",
    "location",
    "transit",
    "education",
    "childcare",
    "healthcare",
    "parks",
    "food",
    "shopping",
}

LOCAL_SOURCE_STATUS = {
    "kind": "local",
    "title": "HomeLens data coverage and capability status",
    "url": "",
}
LOCAL_SOURCE_HDB = {
    "kind": "local",
    "title": "HDB resale transaction knowledge base",
    "url": "https://data.gov.sg/collections/189/view",
}
LOCAL_SOURCE_LISTINGS = {
    "kind": "local",
    "title": "Periodic partial PropertyGuru listing snapshot",
    "url": "https://www.propertyguru.com.sg/",
}
LOCAL_SOURCE_COMMUNITY = {
    "kind": "local",
    "title": "HomeLens aggregate planning-area and subzone evidence",
    "url": "",
}
LOCAL_SOURCE_ONEMAP = {
    "kind": "local",
    "title": "OneMap confirmed Singapore location",
    "url": "https://www.onemap.gov.sg/",
}


def _contains_cjk(value: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", value))


def _clean_text(value: Any, *, maximum: int = 240) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split()).strip()
    return cleaned[:maximum] or None


def _clean_multiline_text(value: Any, *, maximum: int = 6_000) -> str | None:
    """Trim model prose without destroying its Markdown block structure."""
    if not isinstance(value, str):
        return None
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = "\n".join(line.rstrip() for line in normalized.split("\n")).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned[:maximum] or None


def _finite_number(
    value: Any,
    *,
    minimum: float = 0,
    maximum: float = 20_000_000,
) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or not minimum <= number <= maximum:
        return None
    return number


def _safe_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def _dedupe_sources(sources: list[dict[str, Any]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        kind = "web" if source.get("kind") == "web" else "local"
        title = str(source.get("title") or "").strip()
        url = str(source.get("url") or "").strip()
        if not title:
            continue
        key = (kind, title.casefold(), url)
        if key in seen:
            continue
        seen.add(key)
        result.append({"kind": kind, "title": title, "url": url})
    return result


def _towns_from_text(text: str) -> list[str]:
    lower = text.casefold()
    phrases = {town.casefold(): town for town in HDB_TOWNS}
    phrases.update({alias.casefold(): town for alias, town in TOWN_ALIASES.items()})
    matches: list[str] = []
    for phrase, town in sorted(phrases.items(), key=lambda item: len(item[0]), reverse=True):
        if phrase in lower and town not in matches:
            matches.append(town)
    return matches


def _normalise_towns(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    aliases = {town.casefold(): town for town in HDB_TOWNS}
    aliases.update({alias.casefold(): town for alias, town in TOWN_ALIASES.items()})
    result: list[str] = []
    for value in values:
        cleaned = _clean_text(value, maximum=80)
        if not cleaned:
            continue
        canonical = aliases.get(cleaned.casefold(), cleaned.upper())
        if canonical in HDB_TOWNS and canonical not in result:
            result.append(canonical)
    return result[:5]


def _normalise_flat_types(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for value in values:
        cleaned = str(value).strip().upper().replace("-", " ")
        cleaned = re.sub(r"\s+", " ", cleaned)
        match = re.fullmatch(r"([1-5])\s*ROOMS?", cleaned)
        if match:
            cleaned = f"{match.group(1)} ROOM"
        if cleaned in ALLOWED_FLAT_TYPES and cleaned not in result:
            result.append(cleaned)
    return result[:5]


def _normalise_plan(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    intent = str(raw.get("intent") or "general_housing")
    if intent not in PLAN_INTENTS:
        intent = "general_housing"
    mode = str(raw.get("housing_mode") or "unknown")
    if mode not in HOUSING_MODES:
        mode = "unknown"
    scope = raw.get("rental_scope")
    if scope not in RENTAL_SCOPES:
        scope = None
    language = str(raw.get("language") or "other")
    if language not in {"zh", "en", "other"}:
        language = "other"
    sort_by = str(raw.get("sort_by") or "default")
    if sort_by not in SORT_OPTIONS:
        sort_by = "default"
    refinement_type = str(raw.get("refinement_type") or "none")
    if refinement_type not in REFINEMENT_TYPES:
        refinement_type = "none"
    bedrooms: list[int] = []
    if isinstance(raw.get("bedrooms"), list):
        for item in raw["bedrooms"]:
            value = _finite_number(item, minimum=1, maximum=10)
            if value is not None and value.is_integer() and int(value) not in bedrooms:
                bedrooms.append(int(value))
    priorities = [
        str(item)
        for item in raw.get("priorities", [])
        if str(item) in PRIORITIES
    ][:8]
    return {
        "intent": intent,
        "language": language,
        "housing_mode": mode,
        "budget": _finite_number(raw.get("budget"), minimum=100),
        "flat_types": _normalise_flat_types(raw.get("flat_types")),
        "bedrooms": bedrooms[:5],
        "rental_scope": scope,
        "preferred_towns": _normalise_towns(raw.get("preferred_towns")),
        "location_query": _clean_text(raw.get("location_query"), maximum=200),
        "radius_m": _finite_number(raw.get("radius_m"), minimum=100, maximum=50_000),
        "priorities": list(dict.fromkeys(priorities)),
        "wants_recommendations": bool(raw.get("wants_recommendations")),
        "wants_listings": bool(raw.get("wants_listings")),
        "wants_more_options": bool(raw.get("wants_more_options")),
        "exclude_previous_results": bool(raw.get("exclude_previous_results")),
        "sort_by": sort_by,
        "refinement_type": refinement_type,
        "referenced_listing_id": _clean_text(raw.get("referenced_listing_id"), maximum=120),
        "needs_current_web": bool(raw.get("needs_current_web")),
        "clear_budget": bool(raw.get("clear_budget")),
        "clear_location": bool(raw.get("clear_location")),
        "clear_rooms": bool(raw.get("clear_rooms")),
    }


def _rule_plan(message: str) -> dict[str, Any]:
    lower = message.casefold()
    parsed = parse_with_rules(message).values
    budget_free_request = bool(
        re.search(
            r"不在意预算|预算无所谓|钱不是问题|我很有钱|预算不限|不限预算|没有预算上限|"
            r"no budget limit|no upper budget|budget does(?:n't| not) matter",
            lower,
        )
    )
    help_request = bool(
        re.search(
            r"怎么(?:用|使用)|如何(?:用|使用)|使用方法|能做什么|有哪些功能|"
            r"how (?:do i |to )?use|what can (?:you|this)|help me use",
            lower,
        )
    )
    recommendation_request = bool(
        re.search(
            r"推荐|有什么房|哪些房|给我.*(?:选择|房源)|recommend|suggest|options?|"
            r"what (?:homes?|houses?|flats?)",
            lower,
        )
    )
    listing_request = bool(
        re.search(
            r"房源|挂牌|在售|出租|能租到|available|listing|for rent|for sale",
            lower,
        )
    )
    more_options_request = bool(
        re.search(
            r"其他|别的|还有|换一批|更多|重新推荐|another|other|more options?|show me more|"
            r"different options?|anything else",
            lower,
        )
    )
    compare_request = bool(
        re.search(
            r"比较|对比|还是|哪个好|versus|\bvs\.?\b|compare",
            lower,
        )
    )
    current_request = bool(
        re.search(
            r"今天|现在|目前|最新|新闻|政策|法律|利率|签证|"
            r"\btoday\b|\bcurrent(?:ly)?\b|\blatest\b|news|policy|law|interest rate|visa",
            lower,
        )
    )
    external_current_request = bool(
        re.search(
            r"新闻|政策|法律|利率|签证|news|policy|law|interest rate|visa",
            lower,
        )
    )
    rent = bool(re.search(r"租房|租金|月租|出租|\brent(?:al|ing)?\b|lease a", lower))
    buy = bool(
        re.search(
            r"买房|购房|在售|转售|房价|\bbuy(?:ing)?\b|purchase|resale|for sale",
            lower,
        )
    )
    mode = "both" if rent and buy else "rent" if rent else "buy" if buy else "unknown"
    towns = _towns_from_text(message)

    if help_request:
        intent = "help"
    elif compare_request and len(towns) >= 2:
        intent = "area_compare"
    elif recommendation_request:
        intent = "recommendation"
    elif listing_request:
        intent = "listing_search"
    elif current_request:
        intent = "current_information"
    elif towns:
        intent = "area_analysis"
    elif re.search(
        r"行情|市场|大盘|中位数|平均|趋势|market|overview|median|average",
        lower,
    ):
        intent = "market_overview"
    elif re.search(r"历史成交|成交价|historical|transaction", lower):
        intent = "historical_price"
    else:
        intent = "general_housing"

    budget = _finite_number(parsed.get("budget"), minimum=100)
    if budget is None and (rent or re.search(r"预算|价格|多少钱|budget|cost|price", lower)):
        match = re.search(
            r"(?:预算|每月|月租|不超过|最多|大约|约|sgd|s\$|\$)\s*"
            r"([\d,]{3,10})(?:\s*(?:新币|块|左右))?",
            lower,
        )
        if match:
            budget = _finite_number(match.group(1).replace(",", ""), minimum=100)

    location_query = _clean_text(parsed.get("location_query"), maximum=200)
    if not location_query and not towns:
        named_places = {
            "nus": "National University of Singapore",
            "国大": "National University of Singapore",
            "新加坡国立大学": "National University of Singapore",
            "ntu": "Nanyang Technological University",
            "南大": "Nanyang Technological University",
            "南洋理工大学": "Nanyang Technological University",
            "vivocity": "VivoCity",
            "樟宜机场": "Changi Airport",
            "changi airport": "Changi Airport",
        }
        for phrase, canonical in sorted(
            named_places.items(), key=lambda item: len(item[0]), reverse=True
        ):
            if phrase in lower:
                location_query = canonical
                break

    priorities: list[str] = []
    keyword_map = {
        "affordability": ("便宜", "预算", "性价比", "affordable", "cheap"),
        "space": ("空间", "面积", "宽敞", "spacious", "large"),
        "transit": ("地铁", "交通", "通勤", "mrt", "transit", "commute"),
        "education": ("学校", "教育", "school", "education"),
        "childcare": ("幼儿园", "托儿", "childcare", "kindergarten"),
        "healthcare": ("医院", "诊所", "医疗", "hospital", "clinic"),
        "parks": ("公园", "自然", "park", "nature"),
        "food": ("吃饭", "餐饮", "食阁", "food", "hawker"),
        "shopping": ("购物", "商场", "shopping", "mall"),
    }
    for priority, keywords in keyword_map.items():
        if any(keyword in lower for keyword in keywords):
            priorities.append(priority)
    if re.search(
        r"房(?:子|间)?.{0,6}大|面积.{0,6}大|特别大|越大越好|大房|大一点|large|spacious|big",
        lower,
    ):
        priorities.append("space")
    large_space_request = "space" in priorities
    sort_by = "floor_area_desc" if large_space_request else "default"
    refinement_type = (
        "more_options"
        if more_options_request
        else "new_search"
        if recommendation_request or listing_request
        else "none"
    )

    radius = _finite_number(parsed.get("max_anchor_distance_m"), minimum=100, maximum=50_000)
    plan = _normalise_plan(
        {
            "intent": intent,
            "language": "zh" if _contains_cjk(message) else "en",
            "housing_mode": mode,
            "budget": budget,
            "flat_types": parsed.get("flat_types", []),
            "bedrooms": [],
            "rental_scope": "room"
            if re.search(r"普通房|单间|房间|common room|private room", lower)
            else "whole_unit"
            if re.search(r"整租|整套|whole unit|entire", lower)
            else None,
            "preferred_towns": towns,
            "location_query": location_query,
            "radius_m": radius,
            "priorities": priorities,
            "wants_recommendations": recommendation_request or more_options_request,
            "wants_listings": listing_request or recommendation_request or more_options_request,
            "wants_more_options": more_options_request,
            "exclude_previous_results": more_options_request,
            "sort_by": sort_by,
            "refinement_type": refinement_type,
            "referenced_listing_id": None,
            "needs_current_web": external_current_request,
            "clear_budget": bool(
                re.search(r"不限预算|没有预算上限|no budget limit", lower)
            ),
            "clear_location": bool(
                re.search(
                    r"不限地区|地点不限|先不管地点|忽略地点|不考虑地点|"
                    r"anywhere|ignore (?:the )?location|no location preference",
                    lower,
                )
            ),
            "clear_rooms": bool(
                re.search(r"房型不限|卧室不限|any room|any flat type", lower)
            ),
        }
    )
    if large_space_request and plan["rental_scope"] is None:
        plan["rental_scope"] = "whole_unit"
    if budget_free_request:
        plan["clear_budget"] = True
    if plan["housing_mode"] == "rent" and (plan["priorities"] or plan["clear_budget"]):
        plan["wants_recommendations"] = True
        plan["wants_listings"] = True
        if plan["refinement_type"] == "none":
            plan["refinement_type"] = "new_search"
    return plan


def _reconcile_plans(
    model_plan: dict[str, Any],
    rule_plan: dict[str, Any],
) -> dict[str, Any]:
    """Keep clear deterministic signals when the semantic planner omits them."""

    result = dict(model_plan)
    for field in (
        "budget",
        "rental_scope",
        "location_query",
        "radius_m",
    ):
        if result.get(field) is None and rule_plan.get(field) is not None:
            result[field] = rule_plan[field]
    for field in ("flat_types", "bedrooms", "preferred_towns", "priorities"):
        if not result.get(field) and rule_plan.get(field):
            result[field] = rule_plan[field]
    if result.get("housing_mode") == "unknown" and rule_plan.get("housing_mode") != "unknown":
        result["housing_mode"] = rule_plan["housing_mode"]
    for field in (
        "wants_recommendations",
        "wants_listings",
        "wants_more_options",
        "exclude_previous_results",
        "needs_current_web",
        "clear_budget",
        "clear_location",
        "clear_rooms",
    ):
        result[field] = bool(result.get(field) or rule_plan.get(field))
    if result.get("sort_by") == "default" and rule_plan.get("sort_by") != "default":
        result["sort_by"] = rule_plan["sort_by"]
    if (
        result.get("refinement_type") == "none"
        and rule_plan.get("refinement_type") != "none"
    ):
        result["refinement_type"] = rule_plan["refinement_type"]
    if not result.get("referenced_listing_id") and rule_plan.get("referenced_listing_id"):
        result["referenced_listing_id"] = rule_plan["referenced_listing_id"]
    if rule_plan.get("intent") == "help":
        result["intent"] = "help"
    elif rule_plan.get("wants_recommendations") and result.get("intent") in {
        "general_housing",
        "market_overview",
    }:
        result["intent"] = "recommendation"
    elif rule_plan.get("wants_listings") and result.get("intent") == "general_housing":
        result["intent"] = "listing_search"
    if result.get("language") == "other" and rule_plan.get("language") in {"zh", "en"}:
        result["language"] = rule_plan["language"]
    return _normalise_plan(result)


@dataclass
class AgentMemory:
    language: str | None = None
    housing_mode: str | None = None
    max_budget: float | None = None
    flat_types: list[str] = field(default_factory=list)
    bedrooms: list[int] = field(default_factory=list)
    rental_scope: str | None = None
    preferred_towns: list[str] = field(default_factory=list)
    location_query: str | None = None
    anchor_name: str | None = None
    anchor_address: str | None = None
    anchor_latitude: float | None = None
    anchor_longitude: float | None = None
    anchor_planning_area: str | None = None
    anchor_subzone: str | None = None
    max_distance_m: float | None = None
    priorities: list[str] = field(default_factory=list)

    def merge(self, plan: dict[str, Any]) -> None:
        if plan["language"] in {"zh", "en"}:
            self.language = plan["language"]
        if plan["housing_mode"] in {"rent", "buy", "both"}:
            self.housing_mode = plan["housing_mode"]
        if plan["clear_budget"]:
            self.max_budget = None
        elif plan["budget"] is not None:
            self.max_budget = float(plan["budget"])
        if plan["clear_rooms"]:
            self.flat_types = []
            self.bedrooms = []
            self.rental_scope = None
        else:
            if plan["flat_types"]:
                self.flat_types = list(plan["flat_types"])
            if plan["bedrooms"]:
                self.bedrooms = list(plan["bedrooms"])
            if plan["rental_scope"] is not None:
                self.rental_scope = plan["rental_scope"]
        if plan["clear_location"]:
            self.preferred_towns = []
            self.location_query = None
            self.clear_anchor()
        else:
            if plan["preferred_towns"]:
                self.preferred_towns = list(plan["preferred_towns"])
            if plan["location_query"]:
                changed = (
                    self.location_query is None
                    or self.location_query.casefold() != plan["location_query"].casefold()
                )
                self.location_query = plan["location_query"]
                if changed:
                    self.clear_anchor()
        if plan["radius_m"] is not None:
            self.max_distance_m = float(plan["radius_m"])
        if plan["priorities"]:
            self.priorities = list(
                dict.fromkeys([*self.priorities, *plan["priorities"]])
            )[:8]

    def clear_anchor(self) -> None:
        self.anchor_name = None
        self.anchor_address = None
        self.anchor_latitude = None
        self.anchor_longitude = None
        self.anchor_planning_area = None
        self.anchor_subzone = None

    def public(self) -> dict[str, Any]:
        mode = self.housing_mode
        return {
            "housing_mode": "undecided" if mode == "both" else mode,
            "language": self.language,
            "preferred_towns": list(self.preferred_towns),
            "location_raw": self.location_query,
            "location_query": self.location_query,
            "location_resolution_status": (
                "confirmed"
                if self.anchor_latitude is not None
                else "recognized"
                if self.location_query
                else "confirmed"
                if self.preferred_towns
                else "missing"
            ),
            "anchor_name": self.anchor_name,
            "anchor_address": self.anchor_address,
            "anchor_latitude": self.anchor_latitude,
            "anchor_longitude": self.anchor_longitude,
            "anchor_planning_area": self.anchor_planning_area,
            "anchor_subzone": self.anchor_subzone,
            "max_anchor_distance_m": self.max_distance_m,
            "max_budget": self.max_budget,
            "budget_flexible": False,
            "hdb_flat_type": self.flat_types[0] if self.flat_types else None,
            "hdb_flat_types": list(self.flat_types),
            "bedrooms": self.bedrooms[0] if self.bedrooms else None,
            "bedroom_options": list(self.bedrooms),
            "rental_scope": self.rental_scope,
            "room_preference_flexible": False,
            "transport_importance": "high" if "transit" in self.priorities else None,
            "school_need": "important" if "education" in self.priorities else None,
            "childcare_need": "important" if "childcare" in self.priorities else None,
            "healthcare_need": "important" if "healthcare" in self.priorities else None,
            "park_need": "important" if "parks" in self.priorities else None,
            "additional_needs": list(self.priorities),
            "needs_discussed": bool(self.priorities),
        }

    def progress(self) -> dict[str, Any]:
        checks = {
            "housing_mode": self.housing_mode in {"rent", "buy", "both"},
            "location": bool(
                self.preferred_towns
                or self.location_query
                or self.anchor_latitude is not None
            ),
            "maximum_budget": self.max_budget is not None,
            "rooms": bool(self.flat_types or self.bedrooms or self.rental_scope),
            "extra_needs": bool(self.priorities),
        }
        return {
            "completed": sum(checks.values()),
            "total": len(checks),
            "checks": checks,
            "missing": [key for key, value in checks.items() if not value],
            "ready": True,
        }


@dataclass
class GeneralAgentSession:
    session_id: str
    memory: AgentMemory = field(default_factory=AgentMemory)
    turns: list[dict[str, Any]] = field(default_factory=list)
    pending_locations: list[dict[str, Any]] = field(default_factory=list)
    pending_plan: dict[str, Any] | None = None
    pending_message: str | None = None
    updated_at: float = field(default_factory=time.monotonic)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def add_turn(self, role: str, content: str, **metadata: Any) -> None:
        turn = {"role": role, "content": content[:6_000]}
        for key in ("sources", "warnings", "cards"):
            if metadata.get(key):
                turn[key] = metadata[key]
        self.turns.append(turn)
        self.turns = self.turns[-16:]
        self.updated_at = time.monotonic()


class GeneralAgentSessionStore:
    def __init__(self, *, ttl_seconds: int = 14_400, maximum_sessions: int = 256) -> None:
        self.ttl_seconds = ttl_seconds
        self.maximum_sessions = maximum_sessions
        self._sessions: dict[str, GeneralAgentSession] = {}
        self._lock = threading.Lock()

    def _clean(self) -> None:
        cutoff = time.monotonic() - self.ttl_seconds
        expired = [
            key for key, session in self._sessions.items()
            if session.updated_at < cutoff
        ]
        for key in expired:
            self._sessions.pop(key, None)

    def create(self) -> GeneralAgentSession:
        with self._lock:
            self._clean()
            if len(self._sessions) >= self.maximum_sessions:
                oldest = min(
                    self._sessions,
                    key=lambda key: self._sessions[key].updated_at,
                )
                self._sessions.pop(oldest, None)
            session = GeneralAgentSession(session_id=uuid4().hex)
            self._sessions[session.session_id] = session
            return session

    def get(self, session_id: str | None) -> GeneralAgentSession:
        if not session_id:
            return self.create()
        if not re.fullmatch(r"[a-f0-9]{32}", session_id):
            raise ValueError("invalid agent session id")
        with self._lock:
            self._clean()
            session = self._sessions.get(session_id)
            if session is None:
                raise ValueError("agent session expired or was not found")
            session.updated_at = time.monotonic()
            return session

    def delete(self, session_id: str) -> None:
        if not re.fullmatch(r"[a-f0-9]{32}", session_id):
            raise ValueError("invalid agent session id")
        with self._lock:
            self._sessions.pop(session_id, None)


def _recent_listing_cards(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for turn in reversed(turns):
        for card in turn.get("cards") or []:
            if isinstance(card, dict) and card.get("kind") == "listing":
                cards.append(card)
    return cards


def _referenced_listing_card(
    message: str,
    turns: list[dict[str, Any]],
    listing_id: str | None = None,
) -> dict[str, Any] | None:
    if listing_id:
        normalized_id = listing_id.strip().casefold()
        for card in _recent_listing_cards(turns):
            if str(card.get("id") or "").strip().casefold() == normalized_id:
                return card
    normalized = message.casefold()
    for card in _recent_listing_cards(turns):
        candidates = [str(card.get("title") or ""), str(card.get("id") or "")]
        for candidate in candidates:
            cleaned = candidate.strip().casefold()
            if cleaned and cleaned in normalized:
                return card
    if re.search(r"这个|这套|这间|this one|this listing|that one|it\b", normalized):
        for turn in reversed(turns):
            if turn.get("role") != "assistant":
                continue
            content = str(turn.get("content") or "").casefold()
            for card in _recent_listing_cards([turn]):
                title = str(card.get("title") or "").strip().casefold()
                if title and title in content:
                    return card
    return None


def _message_asks_about_place_anchor(message: str) -> bool:
    lower = message.casefold()
    return bool(
        re.search(
            r"附近|靠近|周边|旁边|以.{0,12}为中心|near|around|close to|within",
            lower,
        )
    )


class OpenAIGeneralAgentClient:
    """Two-pass Responses API client: plan local tools, then answer from evidence."""

    def __init__(self, settings: Settings, timeout_seconds: int = 75) -> None:
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
    def _plan_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "intent": {"type": "string", "enum": sorted(PLAN_INTENTS)},
                "language": {"type": "string", "enum": ["zh", "en", "other"]},
                "housing_mode": {"type": "string", "enum": sorted(HOUSING_MODES)},
                "budget": _nullable({"type": "number"}),
                "flat_types": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(ALLOWED_FLAT_TYPES)},
                },
                "bedrooms": {"type": "array", "items": {"type": "integer"}},
                "rental_scope": _nullable(
                    {"type": "string", "enum": sorted(RENTAL_SCOPES)}
                ),
                "preferred_towns": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(HDB_TOWNS)},
                },
                "location_query": _nullable({"type": "string"}),
                "radius_m": _nullable({"type": "number"}),
                "priorities": {
                    "type": "array",
                    "items": {"type": "string", "enum": sorted(PRIORITIES)},
                },
                "wants_recommendations": {"type": "boolean"},
                "wants_listings": {"type": "boolean"},
                "wants_more_options": {"type": "boolean"},
                "exclude_previous_results": {"type": "boolean"},
                "sort_by": {"type": "string", "enum": sorted(SORT_OPTIONS)},
                "refinement_type": {"type": "string", "enum": sorted(REFINEMENT_TYPES)},
                "referenced_listing_id": _nullable({"type": "string"}),
                "needs_current_web": {"type": "boolean"},
                "clear_budget": {"type": "boolean"},
                "clear_location": {"type": "boolean"},
                "clear_rooms": {"type": "boolean"},
            },
            "required": [
                "intent",
                "language",
                "housing_mode",
                "budget",
                "flat_types",
                "bedrooms",
                "rental_scope",
                "preferred_towns",
                "location_query",
                "radius_m",
                "priorities",
                "wants_recommendations",
                "wants_listings",
                "wants_more_options",
                "exclude_previous_results",
                "sort_by",
                "refinement_type",
                "referenced_listing_id",
                "needs_current_web",
                "clear_budget",
                "clear_location",
                "clear_rooms",
            ],
            "additionalProperties": False,
        }

    @staticmethod
    def _answer_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "follow_up": _nullable({"type": "string"}),
            },
            "required": ["answer", "follow_up"],
            "additionalProperties": False,
        }

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
        if isinstance(payload.get("output_text"), str):
            return payload["output_text"]
        refusal = None
        for item in payload.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text" and isinstance(
                    content.get("text"), str
                ):
                    return content["text"]
                if content.get("type") == "refusal":
                    refusal = content.get("refusal")
        if refusal:
            raise ValueError(f"OpenAI housing agent refused the request: {refusal}")
        raise ValueError("OpenAI housing agent response did not contain output text")

    @staticmethod
    def _annotations(payload: dict[str, Any]) -> list[dict[str, str]]:
        sources: list[dict[str, str]] = []
        for item in payload.get("output", []):
            for content in item.get("content", []):
                for annotation in content.get("annotations", []):
                    if annotation.get("type") != "url_citation":
                        continue
                    url = str(annotation.get("url") or "")
                    title = str(annotation.get("title") or url)
                    if url.startswith(("http://", "https://")):
                        sources.append({"kind": "web", "title": title, "url": url})
        return sources

    def _send(
        self,
        *,
        instructions: str,
        input_payload: dict[str, Any],
        schema_name: str,
        schema: dict[str, Any],
        allow_web: bool = False,
    ) -> tuple[dict[str, Any], list[dict[str, str]], bool]:
        request_payload: dict[str, Any] = {
            "model": self.settings.openai_model,
            "instructions": instructions,
            "input": json.dumps(input_payload, ensure_ascii=False, default=str),
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                }
            },
        }
        if allow_web and self.settings.enable_web_search:
            request_payload["tools"] = [{"type": "web_search"}]

        def send(payload: dict[str, Any]) -> dict[str, Any]:
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
            return response.json()

        web_unavailable = False
        try:
            response_payload = send(request_payload)
        except requests.HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if "tools" not in request_payload or status not in {400, 404, 422}:
                raise
            retry = dict(request_payload)
            retry.pop("tools", None)
            response_payload = send(retry)
            web_unavailable = True
        result = json.loads(self._extract_text(response_payload))
        if not isinstance(result, dict):
            raise ValueError("OpenAI housing agent output must be an object")
        return result, self._annotations(response_payload), web_unavailable

    def plan(
        self,
        message: str,
        memory: AgentMemory,
        turns: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not self.available:
            raise RuntimeError("OpenAI housing agent is not configured")
        instructions = (
            "You are the planning stage of a general Singapore housing agent. Classify the "
            "user's immediate request and extract only the local-data queries needed to answer "
            "it. The product is a ChatGPT-like housing tool, not a questionnaire. A vague request "
            "for recommendations is still answerable and must set wants_recommendations=true; do "
            "not require a complete profile. Use location_query only for a specific landmark, "
            "institution, building or address that needs OneMap. Put HDB towns in preferred_towns. "
            "For rent, budgets are monthly; for buy, budgets are purchase totals. Preserve an "
            "unknown mode when the user did not choose rent or buy. needs_current_web is only for "
            "time-sensitive policies, news, laws, rates or current external facts. Treat natural "
            "refinements as executable search plans: if the user changes preferences or asks for "
            "recommendations, set refinement_type='new_search' and wants_listings=true; if they "
            "ask for other, more, another batch, alternatives or anything else, set "
            "refinement_type='more_options', wants_more_options=true and "
            "exclude_previous_results=true. Map broad wording to priorities, not literal "
            "keywords: spacious, roomy, comfortable, bigger or large means priority 'space' and "
            "usually sort_by='floor_area_desc'; convenient commute or near MRT means priority "
            "'transit' and sort_by='mrt_distance_asc'; budget is flexible, money is not an issue "
            "or no upper limit means clear_budget=true. If the user refers to a previous result, "
            "set referenced_listing_id when recent_result_cards contains the match; do not turn a "
            "previous listing title into location_query unless they explicitly ask to search near "
            "that address. Do not collect "
            "or use protected traits. Never invent coordinates or housing facts. Return strict "
            "JSON."
        )
        result, _, _ = self._send(
            instructions=instructions,
            input_payload={
                "current_optional_memory": memory.public(),
                "recent_conversation": [
                    {"role": item.get("role"), "content": item.get("content")}
                    for item in turns[-8:]
                ],
                "recent_result_cards": _recent_listing_cards(turns)[:8],
                "user_message": message,
            },
            schema_name="general_housing_agent_plan",
            schema=self._plan_schema(),
        )
        return _normalise_plan(result)

    def answer(
        self,
        *,
        message: str,
        memory: AgentMemory,
        turns: list[dict[str, Any]],
        plan: dict[str, Any],
        evidence: dict[str, Any],
        cards: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not self.available:
            raise RuntimeError("OpenAI housing agent is not configured")
        instructions = (
            "You are SG HomeRadar, a general ChatGPT-like assistant specialised in Singapore "
            "renting and buying. Answer the user's immediate question first and in the same "
            "language. LOCAL_EVIDENCE is the only authority for project listings, prices, counts, "
            "distances, areas and recommendations. Never invent or alter a listing, coordinate, "
            "price, route time, eligibility rule or statistic. Distinguish registered historical "
            "transactions from periodic partial asking-price listings. If evidence is missing, say "
            "so. If result cards are provided, summarise the important pattern and refer to the "
            "cards below instead of reproducing every field. A vague recommendation request should "
            "receive useful exploratory results, explicitly labelled non-personalised. follow_up "
            "is "
            "optional and may contain at most one natural question only when it would materially "
            "improve the next answer. Never force profile completion or resume a questionnaire. "
            "Whenever LOCAL_EVIDENCE or a result card contains historical_windows, present the "
            "past-2-year and past-4-year figures separately with explicit labels; never blend the "
            "two windows or describe a candidate-group median as one individual transaction. "
            "For product-help questions, explain how to use the software with concrete example "
            "questions. Format longer answers as readable Markdown: use short paragraphs, put "
            "each list item on its own line, leave a blank line between sections, and use bold "
            "sparingly for short labels. Use web search only for truly current external "
            "information. Return strict JSON."
        )
        result, web_sources, web_unavailable = self._send(
            instructions=instructions,
            input_payload={
                "user_message": message,
                "current_optional_memory": memory.public(),
                "recent_conversation": [
                    {"role": item.get("role"), "content": item.get("content")}
                    for item in turns[-8:]
                ],
                "query_plan": plan,
                "local_evidence": evidence,
                "result_cards": cards,
            },
            schema_name="general_housing_agent_answer",
            schema=self._answer_schema(),
            allow_web=bool(plan.get("needs_current_web")),
        )
        return {
            "answer": _clean_multiline_text(result.get("answer"), maximum=6_000) or "",
            "follow_up": _clean_text(result.get("follow_up"), maximum=600),
            "web_sources": web_sources,
            "web_unavailable": web_unavailable,
        }


class HousingDataTools:
    """Bounded local-data tools used by the general agent."""

    def __init__(self, service: HomeLensService) -> None:
        self.service = service
        self._regions: dict[str, dict[str, Any]] | None = None

    def _region_profiles(self) -> dict[str, dict[str, Any]]:
        if self._regions is None:
            path = PROJECT_ROOT / "map" / "public" / "region-profiles.json"
            payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            profiles = payload.get("profiles")
            self._regions = profiles if isinstance(profiles, dict) else {}
        return self._regions

    def system_status(self) -> dict[str, Any]:
        candidates = self.service._load_candidates()
        candidates_4y = self.service._load_candidates_4y()
        listings = self.service._load_live_listings()
        result = {
            "historical_candidate_rows": int(len(candidates)),
            "historical_candidate_rows_2y": int(len(candidates)),
            "historical_candidate_rows_4y": int(len(candidates_4y)),
            "represented_transactions_2y": int(
                pd.to_numeric(
                    candidates.get("recent_transaction_count"), errors="coerce"
                ).sum()
            ),
            "represented_transactions_4y": int(
                pd.to_numeric(
                    candidates_4y.get("recent_transaction_count"), errors="coerce"
                ).sum()
            ),
            "candidate_towns": int(candidates["town"].nunique()),
            "latest_historical_month": None,
            "sale_snapshot_rows": int((listings.get("mode") == "sale").sum())
            if not listings.empty else 0,
            "rental_snapshot_rows": int((listings.get("mode") == "rent").sum())
            if not listings.empty else 0,
            "planning_areas": int(len(self._region_profiles())),
            "subzones": 332,
            "distance_type": "straight-line Haversine",
            "listing_scope": "periodic partial research snapshot, not complete live inventory",
        }
        if "last_transaction_month" in candidates:
            latest = pd.to_datetime(
                candidates["last_transaction_month"], errors="coerce"
            ).max()
            if pd.notna(latest):
                result["latest_historical_month"] = pd.Timestamp(latest).strftime("%Y-%m")
        status_path = self.service.settings.product_status_path
        if status_path.exists():
            status = json.loads(status_path.read_text(encoding="utf-8"))
            result["product_generated_at"] = status.get("generatedAt")
            live_status = status.get("liveListings") or {}
            result["latest_listing_scrape"] = live_status.get("latestScrape")
            result["known_sale_coverage_gap"] = live_status.get("knownSalePageGap")
        return result

    @staticmethod
    def _price_summary(values: pd.Series) -> dict[str, Any]:
        numeric = pd.to_numeric(values, errors="coerce").dropna()
        if numeric.empty:
            return {"count": 0, "median": None, "p25": None, "p75": None}
        return {
            "count": int(len(numeric)),
            "median": round(float(numeric.median()), 2),
            "p25": round(float(numeric.quantile(0.25)), 2),
            "p75": round(float(numeric.quantile(0.75)), 2),
        }

    @staticmethod
    def _month_label(value: Any) -> str | None:
        parsed = pd.to_datetime(value, errors="coerce")
        return pd.Timestamp(parsed).strftime("%Y-%m") if pd.notna(parsed) else None

    @classmethod
    def _historical_window(
        cls,
        row: Any,
        lookback_months: int,
    ) -> dict[str, Any]:
        label = "Past 2 years" if lookback_months == 24 else "Past 4 years"
        transaction_count = _finite_number(
            row.get("recent_transaction_count"),
            maximum=10_000_000,
        )
        return {
            "label": label,
            "lookback_months": lookback_months,
            "median_resale_price": _safe_value(row.get("median_resale_price")),
            "observed_price_low": _safe_value(row.get("observed_price_low")),
            "observed_price_high": _safe_value(row.get("observed_price_high")),
            "transaction_count": int(transaction_count or 0),
            "first_transaction_month": cls._month_label(
                row.get("first_transaction_month")
            ),
            "last_transaction_month": cls._month_label(
                row.get("last_transaction_month")
            ),
            "annual_trend_pct": _safe_value(row.get("price_trend_pct_annual")),
        }

    @classmethod
    def _candidate_window_summary(
        cls,
        candidates: pd.DataFrame,
        lookback_months: int,
    ) -> dict[str, Any]:
        transactions = pd.to_numeric(
            candidates.get("recent_transaction_count"), errors="coerce"
        )
        first = pd.to_datetime(
            candidates.get("first_transaction_month"), errors="coerce"
        )
        last = pd.to_datetime(
            candidates.get("last_transaction_month"), errors="coerce"
        )
        return {
            "label": "Past 2 years" if lookback_months == 24 else "Past 4 years",
            "lookback_months": lookback_months,
            "candidate_groups": int(len(candidates)),
            "represented_transactions": int(transactions.sum()),
            "candidate_group_median_prices": cls._price_summary(
                candidates.get("median_resale_price", pd.Series(dtype=float))
            ),
            "first_observation_month": (
                cls._month_label(first.min()) if first.notna().any() else None
            ),
            "latest_observation_month": (
                cls._month_label(last.max()) if last.notna().any() else None
            ),
        }

    def market_overview(
        self,
        towns: list[str] | None = None,
        flat_types: list[str] | None = None,
    ) -> dict[str, Any]:
        candidates = self.service._load_candidates().copy()
        candidates_4y = self.service._load_candidates_4y().copy()
        listings = self.service._load_live_listings().copy()
        towns = towns or []
        flat_types = flat_types or []
        if towns:
            candidates = candidates.loc[candidates["town"].isin(towns)]
            candidates_4y = candidates_4y.loc[candidates_4y["town"].isin(towns)]
            if not listings.empty:
                area = listings.get("planning_area", pd.Series("", index=listings.index))
                resolved = listings.get("resolved_town", pd.Series("", index=listings.index))
                listings = listings.loc[area.isin(towns) | resolved.isin(towns)]
        if flat_types:
            candidates = candidates.loc[candidates["flat_type"].isin(flat_types)]
            candidates_4y = candidates_4y.loc[
                candidates_4y["flat_type"].isin(flat_types)
            ]
        sale = listings.loc[listings.get("mode") == "sale"] if not listings.empty else listings
        rent = listings.loc[listings.get("mode") == "rent"] if not listings.empty else listings
        past_2_years = self._candidate_window_summary(candidates, 24)
        past_4_years = self._candidate_window_summary(candidates_4y, 48)
        return {
            "scope_towns": towns,
            "scope_flat_types": flat_types,
            "historical_hdb_windows": {
                "past_2_years": past_2_years,
                "past_4_years": past_4_years,
            },
            # Retained for clients built before the dual-window response.
            "historical_hdb_median": past_2_years[
                "candidate_group_median_prices"
            ],
            "sale_asking_prices": self._price_summary(
                sale.get("asking_price", pd.Series(dtype=float))
            ),
            "monthly_rents": self._price_summary(
                rent.get("price_monthly", pd.Series(dtype=float))
            ),
        }

    def area_profiles(self, towns: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        evidence: list[dict[str, Any]] = []
        cards: list[dict[str, Any]] = []
        profiles = self._region_profiles()
        for town in towns[:5]:
            profile = profiles.get(town)
            if not profile:
                continue
            dimensions = profile.get("dimensions") or {}
            strongest = sorted(
                (
                    (name, float(item.get("score")))
                    for name, item in dimensions.items()
                    if isinstance(item, dict) and item.get("score") is not None
                ),
                key=lambda item: (-item[1], item[0]),
            )[:3]
            market = profile.get("market") or {}
            compact = {
                "name": town,
                "liveability_score": profile.get("liveabilityScore"),
                "strongest_dimensions": [
                    {"dimension": name, "score": score} for name, score in strongest
                ],
                "live_sale_listings": profile.get("liveSaleListings"),
                "live_rental_listings": profile.get("liveRentalListings"),
                "historical_median_hdb_price": market.get("medianHdbPrice"),
                "recent_transactions": market.get("recentTransactions"),
                "latest_transaction_month": market.get("latestTransactionMonth"),
                "facility_counts": profile.get("facilityCounts") or {},
            }
            evidence.append(compact)
            metrics = [
                {
                    "label": name.title(),
                    "value": f"{score:.1f}/100",
                }
                for name, score in strongest
            ]
            if market.get("recentTransactions") is not None:
                metrics.append(
                    {
                        "label": "Recent transactions",
                        "value": f"{int(market['recentTransactions']):,}",
                    }
                )
            cards.append(
                {
                    "kind": "area",
                    "id": f"area:{town}",
                    "title": town.title(),
                    "subtitle": "Planning-area evidence",
                    "mode": None,
                    "price": _safe_value(market.get("medianHdbPrice")),
                    "price_unit": "historical HDB median",
                    "planning_area": town,
                    "subzone": None,
                    "metrics": metrics[:4],
                    "reasons": [
                        f"Aggregate liveability score: "
                        f"{profile.get('liveabilityScore', 'unavailable')}.",
                        (
                            f"Partial snapshot contains "
                            f"{int(profile.get('liveSaleListings') or 0):,} sale and "
                            f"{int(profile.get('liveRentalListings') or 0):,} rental listings."
                        ),
                    ],
                    "latitude": None,
                    "longitude": None,
                }
            )
        return evidence, cards

    def _listing_card(self, row: pd.Series) -> dict[str, Any]:
        payload = self.service._listing_payload(row)
        price = _safe_value(payload.get("price"))
        mode = str(payload.get("mode") or "")
        reasons: list[str] = []
        if price is not None:
            reasons.append(
                f"Asking price is S${float(price):,.0f}"
                + (" per month." if mode == "rent" else ".")
            )
        if payload.get("anchor_distance_m") is not None:
            reasons.append(
                f"Straight-line distance to the confirmed place is "
                f"{float(payload['anchor_distance_m']) / 1_000:.2f} km."
            )
        if payload.get("nearest_mrt_distance_m") is not None:
            reasons.append(
                f"Recorded nearest-MRT distance is "
                f"{float(payload['nearest_mrt_distance_m']):,.0f} m."
            )
        metrics: list[dict[str, str]] = []
        if payload.get("floor_area_sqft") is not None:
            metrics.append(
                {
                    "label": "Floor area",
                    "value": f"{float(payload['floor_area_sqft']):,.0f} sqft",
                }
            )
        if payload.get("nearest_mrt_distance_m") is not None:
            metrics.append(
                {
                    "label": "Recorded MRT",
                    "value": f"{float(payload['nearest_mrt_distance_m']):,.0f} m",
                }
            )
        if payload.get("anchor_distance_m") is not None:
            metrics.append(
                {
                    "label": "From anchor",
                    "value": f"{float(payload['anchor_distance_m']) / 1_000:.2f} km",
                }
            )
        return {
            "kind": "listing",
            "id": str(payload["id"]),
            "title": payload.get("address") or payload.get("title") or "Listing",
            "subtitle": payload.get("room_type") or payload.get("property_type"),
            "mode": mode,
            "price": price,
            "price_unit": "per month" if mode == "rent" else "asking price",
            "planning_area": payload.get("planning_area") or payload.get("town"),
            "subzone": payload.get("subzone"),
            "metrics": metrics,
            "reasons": reasons,
            "latitude": payload.get("latitude"),
            "longitude": payload.get("longitude"),
        }

    def listing_search(
        self,
        mode: str,
        memory: AgentMemory,
        *,
        limit: int = 4,
        broad: bool = False,
        exclude_ids: set[str] | None = None,
        prioritize_space: bool = False,
        sort_by: str = "default",
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
        listings = self.service._load_live_listings()
        frame = listings.loc[listings.get("mode") == mode].copy()
        warnings: list[str] = []
        if frame.empty:
            return {"mode": mode, "matched": 0}, [], warnings
        if exclude_ids:
            listing_ids = frame.get("listing_id", pd.Series("", index=frame.index)).astype(str)
            frame = frame.loc[~listing_ids.isin(exclude_ids)].copy()
            if frame.empty:
                return {"mode": mode, "matched": 0}, [], warnings
        price_column = "price_monthly" if mode == "rent" else "asking_price"
        frame["_price"] = pd.to_numeric(frame.get(price_column), errors="coerce")
        frame = frame.loc[frame["_price"].notna()].copy()
        if memory.max_budget is not None:
            frame = frame.loc[frame["_price"] <= memory.max_budget].copy()
        if memory.preferred_towns:
            area = frame.get("planning_area", pd.Series("", index=frame.index))
            resolved = frame.get("resolved_town", pd.Series("", index=frame.index))
            frame = frame.loc[
                area.isin(memory.preferred_towns)
                | resolved.isin(memory.preferred_towns)
            ].copy()
        if mode == "rent":
            room_type = frame.get("room_type", pd.Series(np.nan, index=frame.index))
            if memory.rental_scope == "room":
                frame = frame.loc[room_type.notna()].copy()
            elif memory.rental_scope == "whole_unit":
                frame = frame.loc[room_type.isna()].copy()
            if memory.bedrooms:
                warnings.append(
                    "The rental snapshot has no reliable bedroom-count field, so bedroom count "
                    "was not silently enforced."
                )
        else:
            target_bedrooms: set[int] = set(memory.bedrooms)
            for flat_type in memory.flat_types:
                match = re.match(r"(\d) ROOM", flat_type)
                if match:
                    target_bedrooms.add(max(1, int(match.group(1)) - 1))
            if target_bedrooms:
                bedrooms = pd.to_numeric(frame.get("bedrooms"), errors="coerce")
                frame = frame.loc[bedrooms.isin(target_bedrooms)].copy()

        frame["_anchor_distance_m"] = np.nan
        if (
            memory.anchor_latitude is not None
            and memory.anchor_longitude is not None
            and not frame.empty
        ):
            coordinates = frame[["resolved_latitude", "resolved_longitude"]].apply(
                pd.to_numeric, errors="coerce"
            )
            valid = coordinates.notna().all(axis=1)
            if valid.any():
                frame.loc[valid, "_anchor_distance_m"] = haversine_matrix(
                    coordinates.loc[valid].to_numpy(float),
                    np.asarray(
                        [[memory.anchor_latitude, memory.anchor_longitude]],
                        dtype=float,
                    ),
                )[:, 0]
            if memory.max_distance_m is not None:
                distance = pd.to_numeric(frame["_anchor_distance_m"], errors="coerce")
                frame = frame.loc[
                    distance.notna() & (distance <= memory.max_distance_m)
                ].copy()

        matched = int(len(frame))
        summary = self._price_summary(frame["_price"])
        summary.update(
            {
                "mode": mode,
                "matched": matched,
                "budget_cap": memory.max_budget,
                "towns": list(memory.preferred_towns),
                "anchor_name": memory.anchor_name,
                "radius_m": memory.max_distance_m,
            }
        )
        if frame.empty:
            return summary, [], warnings

        if broad and memory.max_budget is None and len(frame) >= 20:
            low, high = frame["_price"].quantile([0.02, 0.98])
            frame = frame.loc[frame["_price"].between(low, high)].copy()
        frame["_scraped"] = pd.to_datetime(frame.get("scraped_at"), errors="coerce", utc=True)
        sort_columns: list[str] = []
        ascending: list[bool] = []
        if sort_by == "default" and prioritize_space:
            sort_by = "floor_area_desc"
        if sort_by == "floor_area_desc":
            frame["_floor_area"] = pd.to_numeric(frame.get("floor_area_sqft"), errors="coerce")
            sort_columns.append("_floor_area")
            ascending.append(False)
            if mode == "rent":
                room_type = frame.get("room_type", pd.Series(np.nan, index=frame.index))
                frame["_whole_unit"] = room_type.isna().astype(int)
                sort_columns.insert(0, "_whole_unit")
                ascending.insert(0, False)
        if sort_by == "mrt_distance_asc":
            frame["_mrt_distance"] = pd.to_numeric(
                frame.get("nearest_mrt_distance_m"),
                errors="coerce",
            )
            sort_columns.append("_mrt_distance")
            ascending.append(True)
        if memory.anchor_latitude is not None:
            sort_columns.append("_anchor_distance_m")
            ascending.append(True)
        if sort_by == "price_asc":
            sort_columns.append("_price")
            ascending.append(True)
        elif sort_by == "price_desc":
            sort_columns.append("_price")
            ascending.append(False)
        elif sort_by == "newest":
            sort_columns.append("_scraped")
            ascending.append(False)
        else:
            sort_columns.extend(["_scraped", "_price"])
            ascending.extend([False, True])
        frame = frame.sort_values(sort_columns, ascending=ascending, kind="mergesort")

        chosen: list[pd.Series] = []
        seen_areas: set[str] = set()
        for _, row in frame.iterrows():
            area = str(row.get("planning_area") or row.get("resolved_town") or "")
            if broad and area and area in seen_areas:
                continue
            chosen.append(row)
            if area:
                seen_areas.add(area)
            if len(chosen) >= limit:
                break
        if len(chosen) < limit:
            chosen_ids = {str(item.get("listing_id")) for item in chosen}
            for _, row in frame.iterrows():
                if str(row.get("listing_id")) in chosen_ids:
                    continue
                chosen.append(row)
                if len(chosen) >= limit:
                    break
        return summary, [self._listing_card(row) for row in chosen], warnings

    def historical_recommendations(
        self,
        memory: AgentMemory,
        *,
        limit: int = 3,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
        candidates = self.service._load_candidates()
        candidates_4y = self.service._load_candidates_4y()
        four_year_by_id = candidates_4y.set_index("candidate_id", drop=False)
        budget = memory.max_budget
        warnings: list[str] = []
        if budget is None:
            observed = pd.to_numeric(candidates.get("observed_price_high"), errors="coerce")
            budget = float(observed.max()) if observed.notna().any() else 20_000_000
            warnings.append(
                "No purchase budget was supplied; historical options are exploratory and no "
                "personal budget cap was applied."
            )
        preferences = UserPreferences(
            budget=budget,
            flat_types=tuple(memory.flat_types),
            preferred_towns=tuple(memory.preferred_towns),
            require_preferred_town=bool(memory.preferred_towns),
            anchor_name=memory.anchor_name,
            anchor_latitude=memory.anchor_latitude,
            anchor_longitude=memory.anchor_longitude,
            max_anchor_distance_m=memory.max_distance_m
            if memory.anchor_latitude is not None else None,
        )
        ranking = recommend(candidates, preferences, top_k=limit)
        cards: list[dict[str, Any]] = []
        comparisons: list[dict[str, Any]] = []
        for item in ranking.get("recommendations", []):
            candidate_id = str(item["candidate_id"])
            four_year = (
                four_year_by_id.loc[candidate_id]
                if candidate_id in four_year_by_id.index
                else {}
            )
            if isinstance(four_year, pd.DataFrame):
                four_year = four_year.iloc[0]
            historical_windows = [
                self._historical_window(item, 24),
                self._historical_window(four_year, 48),
            ]
            metrics = [
                {
                    "label": "Typical size",
                    "value": f"{float(item['median_floor_area_sqm']):.0f} sqm",
                },
                {
                    "label": "Remaining lease",
                    "value": f"{float(item['median_remaining_lease_years']):.1f} years",
                },
            ]
            if item.get("nearest_mrt_distance_m") is not None:
                metrics.append(
                    {
                        "label": "Recorded MRT",
                        "value": f"{float(item['nearest_mrt_distance_m']):,.0f} m",
                    }
                )
            reasons = list(item.get("reasons") or [])[:3]
            two_year_price = historical_windows[0]["median_resale_price"]
            four_year_price = historical_windows[1]["median_resale_price"]
            if two_year_price is not None and four_year_price:
                difference = (float(two_year_price) / float(four_year_price) - 1) * 100
                reasons.insert(
                    0,
                    "The 2-year candidate-group median is "
                    f"{abs(difference):.1f}% "
                    f"{'above' if difference >= 0 else 'below'} its 4-year median.",
                )
            cards.append(
                {
                    "kind": "historical",
                    "id": candidate_id,
                    "title": str(item["block_address"]),
                    "subtitle": f"{item['town'].title()} · {item['flat_type']}",
                    "mode": "sale",
                    "price": float(item["median_resale_price"]),
                    "price_unit": "2-year historical median",
                    "planning_area": item["town"],
                    "subzone": None,
                    "metrics": metrics,
                    "historical_windows": historical_windows,
                    "reasons": reasons[:4],
                    "latitude": item.get("latitude"),
                    "longitude": item.get("longitude"),
                }
            )
            comparisons.append(
                {
                    "candidate_id": candidate_id,
                    "block_address": str(item["block_address"]),
                    "town": str(item["town"]),
                    "flat_type": str(item["flat_type"]),
                    "historical_windows": historical_windows,
                }
            )
        return {
            "eligible_candidate_count": ranking.get("eligible_candidate_count"),
            "candidate_groups_2y": int(len(candidates)),
            "candidate_groups_4y": int(len(candidates_4y)),
            "hard_filters": ranking.get("hard_filters"),
            "budget_cap": memory.max_budget,
            "comparisons": comparisons,
        }, cards, warnings + list(ranking.get("warnings") or [])

    def execute(
        self,
        plan: dict[str, Any],
        memory: AgentMemory,
        *,
        exclude_listing_ids: set[str] | None = None,
        referenced_listing: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, str]], list[str]]:
        evidence: dict[str, Any] = {"system_status": self.system_status()}
        if referenced_listing:
            evidence["referenced_listing"] = referenced_listing
        cards: list[dict[str, Any]] = []
        sources: list[dict[str, str]] = [LOCAL_SOURCE_STATUS]
        warnings: list[str] = []
        intent = plan["intent"]

        if intent == "help":
            return evidence, cards, sources, warnings

        if memory.preferred_towns:
            area_evidence, area_cards = self.area_profiles(memory.preferred_towns)
            evidence["areas"] = area_evidence
            if intent in {"area_analysis", "area_compare"}:
                cards.extend(area_cards)
            sources.append(LOCAL_SOURCE_COMMUNITY)

        if intent in {
            "market_overview",
            "historical_price",
            "area_analysis",
            "area_compare",
            "current_information",
            "general_housing",
        }:
            evidence["market_overview"] = self.market_overview(
                memory.preferred_towns,
                memory.flat_types,
            )
            sources.extend([LOCAL_SOURCE_HDB, LOCAL_SOURCE_LISTINGS])

        wants_results = bool(
            plan["wants_recommendations"]
            or plan["wants_listings"]
            or intent in {"recommendation", "listing_search"}
        )
        if wants_results:
            mode = memory.housing_mode or plan["housing_mode"]
            broad = memory.max_budget is None and not memory.preferred_towns
            prioritize_space = (
                "space" in memory.priorities
                or "space" in plan.get("priorities", [])
            )
            sort_by = str(plan.get("sort_by") or "default")
            if sort_by == "default" and prioritize_space:
                sort_by = "floor_area_desc"
            elif sort_by == "default" and (
                "transit" in memory.priorities
                or "transit" in plan.get("priorities", [])
            ):
                sort_by = "mrt_distance_asc"
            if mode in {"rent", "both", "unknown"}:
                summary, listing_cards, tool_warnings = self.listing_search(
                    "rent",
                    memory,
                    limit=3 if mode == "rent" else 2,
                    broad=broad,
                    exclude_ids=exclude_listing_ids,
                    prioritize_space=prioritize_space,
                    sort_by=sort_by,
                )
                evidence["rental_results"] = summary
                cards.extend(listing_cards)
                warnings.extend(tool_warnings)
                sources.append(LOCAL_SOURCE_LISTINGS)
            if mode in {"buy", "both", "unknown"}:
                historical, historical_cards, tool_warnings = (
                    self.historical_recommendations(
                        memory,
                        limit=3 if mode == "buy" else 2,
                    )
                )
                evidence["historical_buy_results"] = historical
                cards.extend(historical_cards)
                warnings.extend(tool_warnings)
                sale_summary, sale_cards, sale_warnings = self.listing_search(
                    "sale",
                    memory,
                    limit=3 if mode == "buy" else 2,
                    broad=broad,
                    exclude_ids=exclude_listing_ids,
                    prioritize_space=prioritize_space,
                    sort_by=sort_by,
                )
                evidence["sale_listing_results"] = sale_summary
                cards.extend(sale_cards)
                warnings.extend(sale_warnings)
                sources.extend([LOCAL_SOURCE_HDB, LOCAL_SOURCE_LISTINGS])

        return (
            evidence,
            cards[:8],
            _dedupe_sources(sources),
            list(dict.fromkeys(warnings)),
        )


class GeneralHousingAgent:
    """Conversation coordinator for the non-questionnaire housing agent."""

    def __init__(self, service: HomeLensService, settings: Settings | None = None) -> None:
        self.service = service
        self.settings = settings or service.settings
        self.sessions = GeneralAgentSessionStore()
        self.client = OpenAIGeneralAgentClient(self.settings)
        self.tools = HousingDataTools(service)

    @staticmethod
    def _fallback_answer(
        message: str,
        plan: dict[str, Any],
        evidence: dict[str, Any],
        cards: list[dict[str, Any]],
        *,
        pending_location: bool = False,
    ) -> tuple[str, str | None]:
        chinese = plan.get("language") == "zh" or _contains_cjk(message)
        status = evidence.get("system_status") or {}
        if pending_location:
            answer = (
                "我已经识别到你提到的是一个具体地点。"
                "为了避免把同名地点或错误坐标用于房源筛选，"
                "请先从下面的 OneMap 候选中确认。"
                "确认后我会直接查询"
                "附近数据并回答原问题。"
                if chinese else
                "I recognised a specific place. Please confirm the intended OneMap result below "
                "so I do not use the wrong coordinate. I will query nearby data and answer the "
                "original question immediately after confirmation."
            )
            return answer, None
        if plan["intent"] == "help":
            if chinese:
                return (
                    "你可以像使用 ChatGPT 一样直接提问，"
                    "不需要先填写完整条件。"
                    "我可以分别查询项目中的 "
                    f"{int(status.get('historical_candidate_rows_2y') or 0):,} 个近2年 "
                    f"和 {int(status.get('historical_candidate_rows_4y') or 0):,} 个近4年 "
                    "HDB 历史候选组、"
                    f"{int(status.get('sale_snapshot_rows') or 0):,} 条买房挂牌和 "
                    f"{int(status.get('rental_snapshot_rows') or 0):,} 条租房挂牌，"
                    "也可以比较区域、"
                    "分析预算、查找地标附近房源或解释推荐依据。\n\n"
                    "例如可以问：“NUS 附近 2500 新币能租到什么？”、"
                    "“比较榜鹅和淡滨尼”、"
                    "“给我看看预算友好的买房选择”，"
                    "或者直接问“有什么房子推荐？”。",
                    None,
                )
            return (
                "Use this like ChatGPT: ask a housing question directly without completing a "
                "form. I can compare the project's past-2-year and past-4-year historical HDB "
                "candidate windows, query partial sale and rental snapshots, area profiles and "
                "OneMap-backed locations. Try “What can I rent near NUS for S$2,500?”, "
                "“Compare Punggol and Tampines”, or simply “Show me some homes to explore.”",
                None,
            )
        if plan["intent"] in {"recommendation", "listing_search"}:
            mode = plan.get("housing_mode")
            if chinese:
                label = (
                    "租房"
                    if mode == "rent"
                    else "买房"
                    if mode == "buy"
                    else "租房和买房"
                )
                answer = (
                    "可以。我已从当前项目数据中整理了 "
                    f"{len(cards)} 个{label}探索结果，见下方卡片。"
                    "如果你还没有给出预算或地点，"
                    "这些是覆盖不同区域的"
                    "探索性样例，不是个人化结论；"
                    "挂牌数据也是定期收集的部分市场快照。"
                )
                if any(card.get("historical_windows") for card in cards):
                    answer += (
                        "\n\n买房历史卡片已把**近2年**和**近4年**的成交统计"
                        "分开列出，便于比较近期水平与较长期基线。"
                    )
                follow_up = (
                    "如果想缩小范围，你更想看租房还是买房？"
                    if mode in {"unknown", "both"}
                    else None
                )
                return answer, follow_up
            answer = (
                f"I found {len(cards)} exploratory result cards in the current project data. "
                "When budget or location is missing, these are varied examples rather than a "
                "personalised conclusion. Listing data is a periodic partial snapshot."
            )
            follow_up = (
                "Would you like to focus on renting or buying?"
                if mode in {"unknown", "both"} else None
            )
            return answer, follow_up
        overview = evidence.get("market_overview") or {}
        history = overview.get("historical_hdb_windows") or {}
        rent = overview.get("monthly_rents") or {}
        sale = overview.get("sale_asking_prices") or {}
        if chinese:
            parts = ["我已经查询了与这次问题相关的项目数据。"]
            for key, label in (
                ("past_2_years", "近2年"),
                ("past_4_years", "近4年"),
            ):
                window = history.get(key) or {}
                prices = window.get("candidate_group_median_prices") or {}
                if prices.get("median") is not None:
                    parts.append(
                        f"\n\n- **{label}历史候选组**：典型成交价中位数约 "
                        f"S${float(prices['median']):,.0f}，"
                        f"覆盖 {int(window.get('candidate_groups') or 0):,} 个候选组、"
                        f"{int(window.get('represented_transactions') or 0):,} 笔成交证据。"
                    )
            if rent.get("median") is not None:
                parts.append(
                    "\n\n当前部分租房快照的月租中位数约为 "
                    f"S${float(rent['median']):,.0f}"
                    f"（样本 {int(rent.get('count') or 0):,} 条）。"
                )
            if sale.get("median") is not None:
                parts.append(
                    f"\n\n买房挂牌价中位数约为 S${float(sale['median']):,.0f}"
                    f"（样本 {int(sale.get('count') or 0):,} 条）。"
                )
            parts.append(
                "\n\n历史数字是候选组统计，不是单笔成交；挂牌数字来自部分市场快照，"
                "都不代表个别房屋估值。"
            )
            return "".join(parts), None
        return (
            "I queried the relevant HomeLens project data for this turn. The figures are based "
            "on registered historical transactions and a periodic partial listing snapshot, not "
            "complete live inventory or an individual valuation.",
            None,
        )

    def _confirm_location(
        self,
        session: GeneralAgentSession,
        candidate_id: str,
    ) -> dict[str, Any]:
        candidate = next(
            (
                item for item in session.pending_locations
                if item.get("id") == candidate_id
            ),
            None,
        )
        if candidate is None:
            raise ValueError("location candidate is no longer available; search again")
        region = self.service._locations().index.locate(
            float(candidate["latitude"]),
            float(candidate["longitude"]),
        )
        if region is None:
            raise ValueError("confirmed location must be inside Singapore")
        memory = session.memory
        memory.anchor_name = str(candidate["name"])
        memory.anchor_address = str(candidate["address"])
        memory.anchor_latitude = float(candidate["latitude"])
        memory.anchor_longitude = float(candidate["longitude"])
        memory.anchor_planning_area = region["planning_area"]
        memory.anchor_subzone = region["subzone"]
        session.pending_locations = []
        return candidate

    def _answer_from_evidence(
        self,
        *,
        message: str,
        session: GeneralAgentSession,
        plan: dict[str, Any],
        evidence: dict[str, Any],
        cards: list[dict[str, Any]],
        sources: list[dict[str, str]],
        warnings: list[str],
        method: str,
        pending_location: bool = False,
    ) -> tuple[str, list[dict[str, str]], list[str], str]:
        if self.client.available:
            try:
                generated = self.client.answer(
                    message=message,
                    memory=session.memory,
                    turns=session.turns,
                    plan=plan,
                    evidence=evidence,
                    cards=cards,
                )
                answer = generated["answer"]
                follow_up = generated.get("follow_up")
                if follow_up and not pending_location:
                    answer = f"{answer}\n\n{follow_up}"
                if pending_location:
                    location_note, _ = self._fallback_answer(
                        message,
                        plan,
                        evidence,
                        cards,
                        pending_location=True,
                    )
                    answer = f"{answer}\n\n{location_note}".strip()
                sources = _dedupe_sources(
                    [*sources, *generated.get("web_sources", [])]
                )
                if generated.get("web_unavailable"):
                    warnings.append(
                        "The configured API relay did not support web search for this turn; "
                        "the answer used local project evidence."
                    )
                return answer, sources, list(dict.fromkeys(warnings)), method
            except (requests.RequestException, ValueError, json.JSONDecodeError):
                method = f"{method}_answer_fallback"
        answer, follow_up = self._fallback_answer(
            message,
            plan,
            evidence,
            cards,
            pending_location=pending_location,
        )
        if follow_up:
            answer = f"{answer}\n\n{follow_up}"
        return answer, sources, list(dict.fromkeys(warnings)), method

    def message(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("agent payload must be an object")
        session_id = payload.get("session_id")
        if session_id is not None and not isinstance(session_id, str):
            raise ValueError("session_id must be text")
        session = self.sessions.get(session_id)
        message = str(payload.get("message") or "").strip()
        if len(message) > 6_000:
            raise ValueError("agent message must be at most 6,000 characters")
        candidate_id = payload.get("confirmed_location_id")
        if candidate_id is not None and not isinstance(candidate_id, str):
            raise ValueError("confirmed_location_id must be text")
        if not message and not candidate_id:
            raise ValueError("provide a message or confirmed_location_id")

        with session.lock:
            if candidate_id:
                candidate = self._confirm_location(session, candidate_id)
                plan = session.pending_plan or _normalise_plan(
                    {
                        "intent": "general_housing",
                        "language": session.memory.language or "other",
                        "housing_mode": session.memory.housing_mode or "unknown",
                    }
                )
                original_message = session.pending_message or (
                    f"Analyse housing near {candidate['name']}"
                )
                session.pending_plan = None
                session.pending_message = None
                session.add_turn(
                    "user",
                    f"Confirmed OneMap location: {candidate['name']}",
                )
                evidence, cards, sources, warnings = self.tools.execute(
                    plan, session.memory
                )
                sources = _dedupe_sources([*sources, LOCAL_SOURCE_ONEMAP])
                reply, sources, warnings, method = self._answer_from_evidence(
                    message=original_message,
                    session=session,
                    plan=plan,
                    evidence=evidence,
                    cards=cards,
                    sources=sources,
                    warnings=warnings,
                    method="openai" if self.client.available else "rules",
                )
            else:
                method = "rules"
                rule_plan = _rule_plan(message)
                plan = rule_plan
                if self.client.available:
                    try:
                        plan = _reconcile_plans(
                            self.client.plan(message, session.memory, session.turns),
                            rule_plan,
                        )
                        method = "openai"
                    except (requests.RequestException, ValueError, json.JSONDecodeError):
                        method = "rules_plan_fallback"
                referenced_listing = _referenced_listing_card(
                    message,
                    session.turns,
                    plan.get("referenced_listing_id"),
                )
                if (
                    referenced_listing
                    and plan.get("location_query")
                    and not _message_asks_about_place_anchor(message)
                ):
                    plan["location_query"] = None
                exclude_listing_ids: set[str] = set()
                if plan.get("wants_more_options") or plan.get("exclude_previous_results"):
                    exclude_listing_ids = {
                        str(card.get("id"))
                        for card in _recent_listing_cards(session.turns)
                        if card.get("id")
                    }
                    if referenced_listing and referenced_listing.get("id"):
                        exclude_listing_ids.add(str(referenced_listing["id"]))
                # A new user message replaces any unconfirmed location choice from an
                # earlier turn; stale candidates must never control a later answer.
                session.pending_locations = []
                session.pending_plan = None
                session.pending_message = None
                session.memory.merge(plan)
                session.add_turn("user", message)

                pending_location = False
                unresolved_location = False
                if (
                    plan.get("location_query")
                    and session.memory.anchor_latitude is None
                    and not plan.get("preferred_towns")
                ):
                    try:
                        session.pending_locations = self.service.search_locations(
                            plan["location_query"],
                            limit=5,
                        )["candidates"]
                    except (DataUnavailableError, requests.RequestException, ValueError):
                        session.pending_locations = []
                    if session.pending_locations:
                        pending_location = True
                        session.pending_plan = plan
                        session.pending_message = message
                    else:
                        unresolved_location = True
                if pending_location:
                    evidence = {"system_status": self.tools.system_status()}
                    cards = []
                    sources = [LOCAL_SOURCE_STATUS, LOCAL_SOURCE_ONEMAP]
                    warnings = []
                else:
                    evidence, cards, sources, warnings = self.tools.execute(
                        plan,
                        session.memory,
                        exclude_listing_ids=exclude_listing_ids,
                        referenced_listing=referenced_listing,
                    )
                    if unresolved_location:
                        warnings.append(
                            "The named place could not be confirmed with OneMap, so no "
                            "place-radius filter was applied."
                        )
                reply, sources, warnings, method = self._answer_from_evidence(
                    message=message,
                    session=session,
                    plan=plan,
                    evidence=evidence,
                    cards=cards,
                    sources=sources,
                    warnings=warnings,
                    method=method,
                    pending_location=pending_location,
                )

            session.add_turn(
                "assistant",
                reply,
                sources=sources,
                warnings=warnings,
                cards=cards,
            )
            return {
                "session_id": session.session_id,
                "reply": reply,
                "profile": session.memory.public(),
                "progress": session.memory.progress(),
                "location_candidates": list(session.pending_locations),
                "recommendations": None,
                "cards": cards,
                "sources": sources,
                "warnings": warnings,
                "method": method,
                "privacy": (
                    "Conversation context and the latest 16 turns stay only in this server "
                    "process for up to four hours. Nothing is written to project files. When "
                    "AI is enabled, "
                    "the current message and bounded evidence are sent to the configured provider "
                    "with response storage disabled; provider safety-log policies may still apply."
                ),
            }

    def reset(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = payload.get("session_id") if isinstance(payload, dict) else None
        if not isinstance(session_id, str):
            raise ValueError("session_id is required")
        self.sessions.delete(session_id)
        return {"status": "reset"}

    def state(self, session_id: str) -> dict[str, Any]:
        if not session_id:
            raise ValueError("session_id is required")
        session = self.sessions.get(session_id)
        with session.lock:
            return {
                "session_id": session.session_id,
                "profile": session.memory.public(),
                "progress": session.memory.progress(),
                "turns": list(session.turns),
                "location_candidates": list(session.pending_locations),
                "privacy": (
                    "Conversation context and the latest 16 turns stay only in this server "
                    "process for up to four hours. Nothing is written to project files. When "
                    "AI is enabled, "
                    "the current message and bounded evidence are sent to the configured provider "
                    "with response storage disabled; provider safety-log policies may still apply."
                ),
            }
