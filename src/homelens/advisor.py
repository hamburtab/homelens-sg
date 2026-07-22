"""Privacy-bounded conversational housing advisor over verified project data."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path
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
from homelens.geospatial import _geojson_points, haversine_matrix
from homelens.intent import HDB_TOWNS, parse_with_rules

if TYPE_CHECKING:
    from homelens.service import HomeLensService


NEED_LEVELS = {"no", "optional", "important"}
IMPORTANCE_LEVELS = {"low", "medium", "high"}
HOUSING_MODES = {"rent", "buy", "undecided"}
RENTAL_SCOPES = {"room", "whole_unit", "flexible"}
LOCATION_REASONS = {"explicit", "inferred_from_institution", "inferred_from_workplace"}
FLAT_TYPES = {"2 ROOM", "3 ROOM", "4 ROOM", "5 ROOM", "EXECUTIVE"}
LOCAL_SOURCE_HDB = {
    "kind": "local",
    "title": "data.gov.sg HDB resale transaction snapshot",
    "url": "https://data.gov.sg/collections/189/view",
}
LOCAL_SOURCE_LISTINGS = {
    "kind": "local",
    "title": "Permissioned periodic PropertyGuru research snapshot",
    "url": "",
}
LOCAL_SOURCE_COMMUNITY = {
    "kind": "local",
    "title": "HomeRadar aggregate subzone community evidence",
    "url": "",
}
LOCAL_SOURCE_OSM = {
    "kind": "local",
    "title": "OpenStreetMap point-of-interest snapshot",
    "url": "https://www.openstreetmap.org/",
}


def _finite_number(value: Any, *, minimum: float, maximum: float) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and minimum <= number <= maximum else None


def _clean_text(value: Any, *, maximum: int = 240) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split()).strip()
    return text[:maximum] if text else None


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text))


@dataclass
class HousingProfile:
    housing_mode: str | None = None
    language: str | None = None
    life_stage: str | None = None
    household_summary: str | None = None
    institution: str | None = None
    workplace: str | None = None
    preferred_towns: list[str] = field(default_factory=list)
    location_query: str | None = None
    location_reason: str | None = None
    anchor_name: str | None = None
    anchor_address: str | None = None
    anchor_latitude: float | None = None
    anchor_longitude: float | None = None
    anchor_planning_area: str | None = None
    anchor_subzone: str | None = None
    max_anchor_distance_m: float | None = None
    estimated_budget: float | None = None
    max_budget: float | None = None
    hdb_flat_type: str | None = None
    bedrooms: int | None = None
    rental_scope: str | None = None
    min_floor_area_sqm: float | None = None
    transport_importance: str | None = None
    school_need: str | None = None
    childcare_need: str | None = None
    healthcare_need: str | None = None
    park_need: str | None = None
    additional_needs: list[str] = field(default_factory=list)
    needs_discussed: bool = False

    @property
    def has_location(self) -> bool:
        return bool(
            (self.anchor_latitude is not None and self.anchor_longitude is not None)
            or self.preferred_towns
        )

    def clear_anchor(self) -> None:
        self.anchor_name = None
        self.anchor_address = None
        self.anchor_latitude = None
        self.anchor_longitude = None
        self.anchor_planning_area = None
        self.anchor_subzone = None

    def merge(self, updates: dict[str, Any]) -> None:
        old_query = self.location_query
        mode = updates.get("housing_mode")
        if mode in HOUSING_MODES:
            self.housing_mode = mode
        language = updates.get("language")
        if language in {"zh", "en", "other"}:
            self.language = language
        for key in (
            "life_stage",
            "household_summary",
            "institution",
            "workplace",
            "location_query",
        ):
            value = _clean_text(updates.get(key))
            if value is not None:
                setattr(self, key, value)
        location_reason = updates.get("location_reason")
        if location_reason in LOCATION_REASONS:
            self.location_reason = location_reason
        towns = updates.get("preferred_towns")
        if isinstance(towns, list):
            valid = [str(item).strip().upper() for item in towns if str(item).strip().upper() in HDB_TOWNS]
            if valid:
                self.preferred_towns = list(dict.fromkeys(valid))[:5]
        for key in ("estimated_budget", "max_budget"):
            value = _finite_number(updates.get(key), minimum=100, maximum=20_000_000)
            if value is not None:
                setattr(self, key, value)
        distance = _finite_number(
            updates.get("max_anchor_distance_m"), minimum=100, maximum=50_000
        )
        if distance is not None:
            self.max_anchor_distance_m = distance
        floor_area = _finite_number(
            updates.get("min_floor_area_sqm"), minimum=5, maximum=1_000
        )
        if floor_area is not None:
            self.min_floor_area_sqm = floor_area
        flat_type = str(updates.get("hdb_flat_type") or "").strip().upper()
        if flat_type in FLAT_TYPES:
            self.hdb_flat_type = flat_type
        bedrooms = _finite_number(updates.get("bedrooms"), minimum=1, maximum=10)
        if bedrooms is not None and bedrooms.is_integer():
            self.bedrooms = int(bedrooms)
        rental_scope = updates.get("rental_scope")
        if rental_scope in RENTAL_SCOPES:
            self.rental_scope = rental_scope
        transport = updates.get("transport_importance")
        if transport in IMPORTANCE_LEVELS:
            self.transport_importance = transport
        for key in ("school_need", "childcare_need", "healthcare_need", "park_need"):
            value = updates.get(key)
            if value in NEED_LEVELS:
                setattr(self, key, value)
        additional = updates.get("additional_needs")
        if isinstance(additional, list):
            clean = [_clean_text(item, maximum=120) for item in additional]
            self.additional_needs = list(
                dict.fromkeys(self.additional_needs + [item for item in clean if item])
            )[:12]
        if updates.get("needs_discussed") is True:
            self.needs_discussed = True
            self.transport_importance = self.transport_importance or "medium"
            for key in ("school_need", "childcare_need", "healthcare_need", "park_need"):
                if getattr(self, key) is None:
                    setattr(self, key, "optional")
        if old_query and self.location_query and old_query.casefold() != self.location_query.casefold():
            self.clear_anchor()

    def public(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AdvisorSession:
    session_id: str
    profile: HousingProfile = field(default_factory=HousingProfile)
    turns: list[dict[str, str]] = field(default_factory=list)
    pending_locations: list[dict[str, Any]] = field(default_factory=list)
    updated_at: float = field(default_factory=time.monotonic)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def add_turn(self, role: str, content: str) -> None:
        self.turns.append({"role": role, "content": content[:4_000]})
        self.turns = self.turns[-12:]
        self.updated_at = time.monotonic()


class AdvisorSessionStore:
    def __init__(self, *, ttl_seconds: int = 14_400, maximum_sessions: int = 256) -> None:
        self.ttl_seconds = ttl_seconds
        self.maximum_sessions = maximum_sessions
        self._sessions: dict[str, AdvisorSession] = {}
        self._lock = threading.Lock()

    def _clean(self) -> None:
        cutoff = time.monotonic() - self.ttl_seconds
        expired = [key for key, item in self._sessions.items() if item.updated_at < cutoff]
        for key in expired:
            self._sessions.pop(key, None)

    def create(self) -> AdvisorSession:
        with self._lock:
            self._clean()
            if len(self._sessions) >= self.maximum_sessions:
                oldest = min(self._sessions, key=lambda key: self._sessions[key].updated_at)
                self._sessions.pop(oldest, None)
            session = AdvisorSession(session_id=uuid4().hex)
            self._sessions[session.session_id] = session
            return session

    def get(self, session_id: str | None) -> AdvisorSession:
        if not session_id:
            return self.create()
        if not re.fullmatch(r"[a-f0-9]{32}", session_id):
            raise ValueError("invalid advisor session id")
        with self._lock:
            self._clean()
            session = self._sessions.get(session_id)
            if session is None:
                raise ValueError("advisor session expired or was not found")
            session.updated_at = time.monotonic()
            return session

    def delete(self, session_id: str) -> None:
        if not re.fullmatch(r"[a-f0-9]{32}", session_id):
            raise ValueError("invalid advisor session id")
        with self._lock:
            self._sessions.pop(session_id, None)


class PointOfInterestIndex:
    CATEGORIES = {
        "schools": "geojson_school.json",
        "kindergartens": "geojson_kindergarten.json",
        "clinics": "geojson_clinic.json",
        "hospitals": "geojson_hospital.json",
        "parks": "geojson_park.json",
    }

    def __init__(self) -> None:
        root = PROJECT_ROOT / "map" / "public" / "geojson"
        self.layers: dict[str, tuple[np.ndarray, list[dict[str, Any]]]] = {
            name: _geojson_points(root / filename)
            for name, filename in self.CATEGORIES.items()
        }

    @staticmethod
    def _name(properties: dict[str, Any]) -> str | None:
        for key in ("name", "NAME", "name:en"):
            value = properties.get(key)
            if value:
                return str(value)
        return None

    def around(self, latitude: float, longitude: float) -> dict[str, Any]:
        result: dict[str, Any] = {}
        origin = np.asarray([[latitude, longitude]], dtype=float)
        for category, (points, properties) in self.layers.items():
            if len(points) == 0:
                continue
            distances = haversine_matrix(origin, points)[0]
            nearest_index = int(np.argmin(distances))
            radius = 3_000 if category == "hospitals" else 1_000
            result[category] = {
                f"count_within_{radius // 1000}km": int((distances <= radius).sum()),
                "nearest_name": self._name(properties[nearest_index]),
                "nearest_distance_m": round(float(distances[nearest_index])),
            }
        return result


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


class OpenAIAdvisorClient:
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
    def _schema() -> dict[str, Any]:
        need = _nullable({"type": "string", "enum": sorted(NEED_LEVELS)})
        updates = {
            "type": "object",
            "properties": {
                "housing_mode": _nullable({"type": "string", "enum": sorted(HOUSING_MODES)}),
                "language": _nullable({"type": "string", "enum": ["zh", "en", "other"]}),
                "life_stage": _nullable({"type": "string"}),
                "household_summary": _nullable({"type": "string"}),
                "institution": _nullable({"type": "string"}),
                "workplace": _nullable({"type": "string"}),
                "preferred_towns": {"type": "array", "items": {"type": "string"}},
                "location_query": _nullable({"type": "string"}),
                "location_reason": _nullable(
                    {"type": "string", "enum": sorted(LOCATION_REASONS)}
                ),
                "max_anchor_distance_m": _nullable({"type": "number"}),
                "estimated_budget": _nullable({"type": "number"}),
                "max_budget": _nullable({"type": "number"}),
                "hdb_flat_type": _nullable({"type": "string"}),
                "bedrooms": _nullable({"type": "integer"}),
                "rental_scope": _nullable(
                    {"type": "string", "enum": sorted(RENTAL_SCOPES)}
                ),
                "min_floor_area_sqm": _nullable({"type": "number"}),
                "transport_importance": _nullable(
                    {"type": "string", "enum": sorted(IMPORTANCE_LEVELS)}
                ),
                "school_need": need,
                "childcare_need": need,
                "healthcare_need": need,
                "park_need": need,
                "additional_needs": {"type": "array", "items": {"type": "string"}},
                "needs_discussed": _nullable({"type": "boolean"}),
            },
            "required": [
                "housing_mode", "language", "life_stage", "household_summary",
                "institution", "workplace", "preferred_towns", "location_query",
                "location_reason", "max_anchor_distance_m", "estimated_budget",
                "max_budget", "hdb_flat_type", "bedrooms", "rental_scope",
                "min_floor_area_sqm", "transport_importance", "school_need",
                "childcare_need", "healthcare_need", "park_need", "additional_needs",
                "needs_discussed",
            ],
            "additionalProperties": False,
        }
        source = {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["local", "web"]},
                "title": {"type": "string"},
                "url": {"type": "string"},
            },
            "required": ["kind", "title", "url"],
            "additionalProperties": False,
        }
        return {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "profile_updates": updates,
                "recommendation_requested": {"type": "boolean"},
                "sources": {"type": "array", "items": source},
            },
            "required": ["answer", "profile_updates", "recommendation_requested", "sources"],
            "additionalProperties": False,
        }

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
        if isinstance(payload.get("output_text"), str):
            return payload["output_text"]
        refusal = None
        for item in payload.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    return content["text"]
                if content.get("type") == "refusal":
                    refusal = content.get("refusal")
        if refusal:
            raise ValueError(f"OpenAI advisor refused the request: {refusal}")
        raise ValueError("OpenAI advisor response did not contain output text")

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

    @staticmethod
    def _needs_web(message: str) -> bool:
        return bool(
            re.search(
                r"\b(today|current|currently|latest|recent news|interest rate|policy|law|visa)\b|"
                r"今天|目前|现在|最新|新闻|利率|政策|法律|签证|学费|开放时间",
                message,
                flags=re.I,
            )
        )

    def respond(
        self,
        message: str,
        profile: HousingProfile,
        turns: list[dict[str, str]],
        local_evidence: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.available:
            raise RuntimeError("OpenAI advisor is not configured")
        instructions = (
            "You are SG HomeRadar's careful Singapore housing advisor. The user may have only a "
            "vague intention to rent or buy. FIRST answer the user's actual question clearly and "
            "in the same language. Do not ask a follow-up inside answer; the application chooses "
            "one next question after your answer. Use LOCAL_EVIDENCE for project facts and label "
            "historical transactions, periodic listing snapshots, aggregate community evidence, "
            "and straight-line distance accurately. Never invent a listing, price, coordinate, "
            "route time, school eligibility, medical claim, or market fact. If evidence is absent, "
            "say so. Update the profile only from what the user explicitly states or from a modest, "
            "transparent housing implication: for example, a student at a named institution may "
            "have location_query set to that institution with location_reason "
            "inferred_from_institution. A named HDB town belongs in preferred_towns; a landmark, "
            "school or workplace belongs in location_query. For rent, budgets are monthly. For buy, "
            "budgets are total purchase budgets. Do not collect diagnoses or use nationality, race, "
            "religion, gender or other protected traits to rank housing. Never copy those traits into "
            "profile_updates, including household_summary, even when the user volunteers them. "
            "school_need means schools for the user's child or dependent; never set it merely because "
            "the user is a university student or wants to live near their own institution. "
            "needs_discussed is true only "
            "after the user has addressed extra household/location needs or said there are none. Set "
            "recommendation_requested when the user directly asks for options/results. Return strict JSON."
        )
        input_payload = {
            "current_profile": profile.public(),
            "recent_conversation": turns[-8:],
            "local_evidence": local_evidence,
            "user_message": message,
        }
        request_payload: dict[str, Any] = {
            "model": self.settings.openai_model,
            "instructions": instructions,
            "input": json.dumps(input_payload, ensure_ascii=False, default=str),
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "housing_advisor_turn",
                    "strict": True,
                    "schema": self._schema(),
                }
            },
        }
        web_requested = self.settings.enable_web_search and self._needs_web(message)
        if web_requested:
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
            if not web_requested or status not in {400, 404, 422}:
                raise
            retry = dict(request_payload)
            retry.pop("tools", None)
            response_payload = send(retry)
            web_unavailable = True
        result = json.loads(self._extract_text(response_payload))
        result["sources"] = list(result.get("sources") or []) + self._annotations(response_payload)
        result["sources"] = _dedupe_sources(result["sources"])
        result["method"] = "openai_web" if any(
            item.get("type") == "web_search_call" for item in response_payload.get("output", [])
        ) else "openai"
        result["web_search_unavailable"] = web_unavailable
        return result


def _dedupe_sources(sources: list[dict[str, Any]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for source in sources:
        kind = str(source.get("kind") or "local")
        title = _clean_text(source.get("title"), maximum=200)
        url = str(source.get("url") or "").strip()
        if kind not in {"local", "web"} or not title:
            continue
        if url and not url.startswith(("http://", "https://")):
            url = ""
        key = (title.casefold(), url)
        if key not in seen:
            seen.add(key)
            result.append({"kind": kind, "title": title, "url": url})
    return result[:10]


def _budget_from_text(text: str) -> float | None:
    patterns = (
        r"(?:最高|最多|上限|预算|不超过|每月|月租)[^\d]{0,8}([\d,.]+)\s*(万|千|k|m)?",
        r"(?:budget|max(?:imum)?|up to|under|per month)[^\d]{0,8}([\d,.]+)\s*(k|m)?",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if not match:
            continue
        value = float(match.group(1).replace(",", ""))
        suffix = (match.group(2) or "").lower()
        if suffix == "万":
            value *= 10_000
        elif suffix in {"千", "k"}:
            value *= 1_000
        elif suffix == "m":
            value *= 1_000_000
        return value if 100 <= value <= 20_000_000 else None
    return None


def _institution_from_text(text: str) -> str | None:
    acronyms = re.search(
        r"(?<![A-Za-z])(NUS|NTU|SMU|SUTD|SIT|SUSS|INSEAD|LASALLE|NAFA)(?![A-Za-z])",
        text,
        re.I,
    )
    if acronyms:
        return acronyms.group(1).upper()
    english = re.search(
        r"(?:study(?:ing)? at|student at|attend(?:ing)?|from)\s+"
        r"([A-Z][A-Za-z&' .-]{2,60}(?:University|College|Institute))",
        text,
        re.I,
    )
    if english:
        return _clean_text(english.group(1), maximum=100)
    chinese = re.search(r"(?:在|就读于)?([A-Za-z\u3400-\u9fff]{2,40}(?:大学|学院))(?:读书|上学|就读|的学生)?", text)
    return _clean_text(chinese.group(1), maximum=100) if chinese else None


def _child_school_need_explicit(text: str) -> bool:
    lower = text.casefold()
    return bool(
        re.search(r"小孩|孩子|子女|学区|小学|中学|child|kid|dependent", lower)
        or re.search(
            r"(?:附近|周边|靠近).{0,8}(?:学校|幼儿园)|"
            r"(?:school|kindergarten).{0,12}(?:nearby|close|walking)",
            lower,
        )
    )


def _rule_profile_updates(text: str, profile: HousingProfile) -> tuple[dict[str, Any], bool]:
    lower = text.casefold()
    updates: dict[str, Any] = {"language": "zh" if _contains_cjk(text) else "en"}
    rent = bool(re.search(r"租房|租住|月租|rent(?:al|ing)?|lease a (?:room|home|flat)", lower))
    buy = bool(re.search(r"买房|购房|置业|buy(?:ing)?|purchase a (?:home|flat)", lower))
    if rent and buy:
        updates["housing_mode"] = "undecided"
    elif rent:
        updates["housing_mode"] = "rent"
    elif buy:
        updates["housing_mode"] = "buy"

    budget = _budget_from_text(text)
    if budget is not None:
        updates["max_budget"] = budget

    rules = parse_with_rules(text)
    if rules.values.get("preferred_towns"):
        updates["preferred_towns"] = list(rules.values["preferred_towns"])
    if rules.values.get("location_query"):
        updates["location_query"] = rules.values["location_query"]
        updates["location_reason"] = "explicit"
    if rules.values.get("max_anchor_distance_m"):
        updates["max_anchor_distance_m"] = rules.values["max_anchor_distance_m"]
    if rules.values.get("min_floor_area_sqm"):
        updates["min_floor_area_sqm"] = rules.values["min_floor_area_sqm"]
    flat_types = rules.values.get("flat_types") or []
    if flat_types:
        updates["hdb_flat_type"] = flat_types[0]

    bedroom = re.search(r"\b(\d)\s*(?:bed|bedroom)s?\b|([一二两三四五六])\s*(?:个)?卧室", text, re.I)
    if bedroom:
        chinese_numbers = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6}
        updates["bedrooms"] = int(bedroom.group(1)) if bedroom.group(1) else chinese_numbers[bedroom.group(2)]

    if re.search(r"普通房|单间|合租|common room|private room|rent a room", lower):
        updates["rental_scope"] = "room"
    elif re.search(r"整租|整套|whole (?:unit|flat|apartment)", lower):
        updates["rental_scope"] = "whole_unit"

    institution = _institution_from_text(text)
    if institution:
        updates["institution"] = institution
        if not updates.get("location_query") and not profile.has_location:
            updates["location_query"] = institution
            updates["location_reason"] = "inferred_from_institution"
        if re.search(r"学生|留学|student|studying", lower):
            updates["life_stage"] = "student"

    if re.search(r"没车|没有车|no car|do not drive|don't drive|公共交通.*重要|靠近地铁", lower):
        updates["transport_importance"] = "high"
    elif re.search(r"交通不重要|有车|drive everywhere", lower):
        updates["transport_importance"] = "low"
    if _child_school_need_explicit(text):
        updates["school_need"] = "important"
    if re.search(r"幼儿园|托儿|kindergarten|childcare", lower):
        updates["childcare_need"] = "important"
    if re.search(r"老人|诊所|医院|医疗|clinic|hospital|healthcare", lower):
        updates["healthcare_need"] = "important"
    if re.search(r"退休|公园|散步|修养|park|nature|quiet", lower):
        updates["park_need"] = "important"
    discussed = bool(
        re.search(
            r"没有(?:其他|额外)?(?:要求|需求)|没别的|就这些|没有了|没了|nothing else|"
            r"no other (?:need|requirement)|交通|小孩|孩子|幼儿园|老人|诊所|医院|公园",
            lower,
        )
    ) or _child_school_need_explicit(text)
    if discussed:
        updates["needs_discussed"] = True
    recommendation_requested = bool(
        re.search(
            r"推荐(?:结果|房|几个|一下)?|给我(?:看看|列出|结果)|直接(?:给|出).*结果|"
            r"recommend|show me (?:options|homes|listings)|give me (?:options|results)",
            lower,
        )
    )
    return updates, recommendation_requested


class HousingAdvisor:
    """Coordinates dialogue, verified tools, profile collection and recommendations."""

    def __init__(self, service: HomeLensService, settings: Settings | None = None) -> None:
        self.service = service
        self.settings = settings or service.settings
        self.sessions = AdvisorSessionStore()
        self.client = OpenAIAdvisorClient(self.settings)
        self._poi: PointOfInterestIndex | None = None
        self._region_profiles: dict[str, dict[str, Any]] | None = None

    def _pois(self) -> PointOfInterestIndex:
        if self._poi is None:
            self._poi = PointOfInterestIndex()
        return self._poi

    def _regions(self) -> dict[str, dict[str, Any]]:
        if self._region_profiles is None:
            path = PROJECT_ROOT / "map" / "public" / "region-profiles.json"
            payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            self._region_profiles = payload.get("profiles") or {}
        return self._region_profiles

    def _local_evidence(self, message: str, profile: HousingProfile) -> dict[str, Any]:
        candidates = self.service._load_candidates()
        listings = self.service._load_live_listings()
        mentioned: list[str] = []
        upper = message.upper()
        for town in HDB_TOWNS:
            if town in upper:
                mentioned.append(town)
        mentioned.extend(profile.preferred_towns)
        if profile.anchor_planning_area:
            mentioned.append(profile.anchor_planning_area)
        mentioned = list(dict.fromkeys(mentioned))[:3]

        areas: list[dict[str, Any]] = []
        for name in mentioned:
            region = self._regions().get(name)
            if region:
                areas.append(region)

        snapshot: dict[str, Any] = {
            "historical_candidate_rows": int(len(candidates)),
            "live_sale_rows": int((listings.get("mode") == "sale").sum()) if not listings.empty else 0,
            "live_rental_rows": int((listings.get("mode") == "rent").sum()) if not listings.empty else 0,
        }
        if mentioned and not listings.empty:
            local = listings.loc[listings.get("planning_area").isin(mentioned)].copy()
            sales = pd.to_numeric(
                local.get("asking_price", pd.Series(np.nan, index=local.index)),
                errors="coerce",
            ).loc[local["mode"] == "sale"]
            rents = pd.to_numeric(
                local.get("price_monthly", pd.Series(np.nan, index=local.index)),
                errors="coerce",
            ).loc[local["mode"] == "rent"]
            snapshot["selected_areas"] = mentioned
            snapshot["sale_listing_count"] = int(sales.notna().sum())
            snapshot["median_sale_asking_price"] = float(sales.median()) if sales.notna().any() else None
            snapshot["rental_listing_count"] = int(rents.notna().sum())
            snapshot["median_monthly_rent"] = float(rents.median()) if rents.notna().any() else None
        if (
            profile.anchor_latitude is not None
            and profile.anchor_longitude is not None
            and not listings.empty
        ):
            coordinates = listings[["resolved_latitude", "resolved_longitude"]].apply(
                pd.to_numeric, errors="coerce"
            )
            valid = coordinates.notna().all(axis=1)
            radius = profile.max_anchor_distance_m or 5_000
            distances = pd.Series(np.nan, index=listings.index)
            if valid.any():
                distances.loc[valid] = haversine_matrix(
                    coordinates.loc[valid].to_numpy(float),
                    np.asarray([[profile.anchor_latitude, profile.anchor_longitude]], dtype=float),
                )[:, 0]
            nearby = listings.loc[distances <= radius]
            rent = pd.to_numeric(
                nearby.get("price_monthly", pd.Series(np.nan, index=nearby.index)),
                errors="coerce",
            ).loc[nearby["mode"] == "rent"]
            sale = pd.to_numeric(
                nearby.get("asking_price", pd.Series(np.nan, index=nearby.index)),
                errors="coerce",
            ).loc[nearby["mode"] == "sale"]
            snapshot["anchor_radius_m"] = radius
            snapshot["anchor_name"] = profile.anchor_name
            snapshot["nearby_rental_count"] = int(rent.notna().sum())
            snapshot["nearby_median_monthly_rent"] = float(rent.median()) if rent.notna().any() else None
            snapshot["nearby_sale_count"] = int(sale.notna().sum())
            snapshot["nearby_median_sale_asking_price"] = float(sale.median()) if sale.notna().any() else None
        return {
            "scope": (
                "Local evidence is a historical HDB candidate knowledge base plus a partial, "
                "periodically collected listing snapshot; it is not complete live inventory."
            ),
            "snapshot": snapshot,
            "area_profiles": areas,
            "distance_type": "straight-line Haversine, never route time",
            "sources": [LOCAL_SOURCE_HDB, LOCAL_SOURCE_LISTINGS, LOCAL_SOURCE_COMMUNITY],
        }

    @staticmethod
    def _fallback_answer(message: str, evidence: dict[str, Any]) -> str:
        chinese = _contains_cjk(message)
        if re.search(r"你好|hello|hi\b", message, re.I):
            return "你好，我会先回答你的问题，再逐步帮你理清租房或买房需求。" if chinese else (
                "Hello. I’ll answer your questions first, then help you clarify a housing plan step by step."
            )
        snapshot = evidence.get("snapshot") or {}
        if re.search(r"多少|价格|租金|price|rent", message, re.I) and snapshot:
            selected = snapshot.get("selected_areas") or []
            rent = snapshot.get("median_monthly_rent")
            sale = snapshot.get("median_sale_asking_price")
            if chinese:
                area_label = f"（{', '.join(selected)}）" if selected else ""
                pieces = [f"我目前能核对的是项目内的定期房源快照{area_label}。"]
                if rent is not None:
                    pieces.append(f"快照中的月租中位数约为 S${rent:,.0f}。")
                if sale is not None:
                    pieces.append(f"买房挂牌价中位数约为 S${sale:,.0f}。")
                return "".join(pieces) + "这些不是完整实时市场报价。"
        return (
            "我记下了这条信息。当前 AI 服务不可用，因此我会继续用确定性规则整理需求，并只依据本地数据给出结果。"
            if chinese else
            "I’ve noted that. The AI service is unavailable, so I’ll continue with deterministic profile rules and verified local evidence."
        )

    @staticmethod
    def _profile_progress(profile: HousingProfile) -> dict[str, Any]:
        mode_ready = profile.housing_mode in {"rent", "buy"}
        rooms_ready = (
            bool(profile.hdb_flat_type or profile.bedrooms)
            if profile.housing_mode == "buy"
            else bool(profile.rental_scope == "room" or profile.bedrooms)
            if profile.housing_mode == "rent"
            else False
        )
        checks = {
            "housing_mode": mode_ready,
            "location": profile.has_location,
            "maximum_budget": profile.max_budget is not None,
            "rooms": rooms_ready,
            "extra_needs": profile.needs_discussed,
        }
        missing = [key for key, ready in checks.items() if not ready]
        return {
            "completed": sum(checks.values()),
            "total": len(checks),
            "checks": checks,
            "missing": missing,
            "ready": not missing,
        }

    @staticmethod
    def _next_question(profile: HousingProfile, progress: dict[str, Any], *, chinese: bool) -> str:
        missing = progress["missing"]
        if not missing:
            return (
                "您还有什么需要补充的吗？如果没有，我将根据目前对您的了解，给您列出最推荐的三处地点和三处真实房源。"
                if chinese else
                "Is there anything else you would like to add? If not, I can now show my three recommended locations and three real listings."
            )
        key = missing[0]
        questions = {
            "housing_mode": (
                "你目前更倾向租房还是买房？如果还没决定，我也可以先帮你比较。",
                "Are you leaning toward renting or buying? I can also help compare them if you are undecided.",
            ),
            "location": (
                "你希望住在哪附近？可以告诉我学校、公司、地标，或者一个新加坡 town。",
                "Where would you like to live near? You can name a school, workplace, landmark, or Singapore town.",
            ),
            "maximum_budget": (
                "你能接受的最高预算是多少？租房请告诉我每月上限，买房请告诉我总价上限。",
                "What is your maximum budget? For rent, give a monthly cap; for buying, give a total purchase cap.",
            ),
            "rooms": (
                "你需要什么房型？租房可以说普通房/整租和卧室数；买房可以说 HDB 3-room、4-room 等。",
                "What room setup do you need? For rent, say room/whole unit and bedrooms; for buying, say the HDB flat type.",
            ),
            "extra_needs": (
                "还有哪些生活需求会影响位置选择？例如公共交通、学校或幼儿园、诊所或医院、公园；没有也可以直接说没有。",
                "What other needs affect location choice—public transport, schools or childcare, clinics or hospitals, or parks? You can also say none.",
            ),
        }
        return questions[key][0 if chinese else 1]

    @staticmethod
    def _need_score(profile: HousingProfile, poi: dict[str, Any]) -> float:
        values: list[float] = []
        mappings = (
            (profile.school_need, "schools", "count_within_1km", 3),
            (profile.childcare_need, "kindergartens", "count_within_1km", 3),
            (profile.healthcare_need, "clinics", "count_within_1km", 4),
            (profile.healthcare_need, "hospitals", "count_within_3km", 2),
            (profile.park_need, "parks", "count_within_1km", 3),
        )
        for need, category, key, target in mappings:
            if need != "important":
                continue
            count = float((poi.get(category) or {}).get(key) or 0)
            values.append(min(1.0, count / target))
        return float(np.mean(values)) if values else 0.5

    @staticmethod
    def _poi_reasons(profile: HousingProfile, poi: dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        if profile.school_need == "important":
            count = (poi.get("schools") or {}).get("count_within_1km", 0)
            reasons.append(f"OSM snapshot records {count} school POIs within 1 km.")
        if profile.childcare_need == "important":
            count = (poi.get("kindergartens") or {}).get("count_within_1km", 0)
            reasons.append(f"OSM snapshot records {count} kindergarten POIs within 1 km.")
        if profile.healthcare_need == "important":
            clinics = (poi.get("clinics") or {}).get("count_within_1km", 0)
            hospital = poi.get("hospitals") or {}
            reasons.append(
                f"OSM snapshot records {clinics} clinic POIs within 1 km; nearest recorded "
                f"hospital is {float(hospital.get('nearest_distance_m') or 0) / 1_000:.1f} km away."
            )
        if profile.park_need == "important":
            parks = poi.get("parks") or {}
            reasons.append(
                f"OSM snapshot records {parks.get('count_within_1km', 0)} park POIs within 1 km."
            )
        return reasons

    def _location_payload(self, row: pd.Series) -> tuple[float | None, float | None]:
        latitude = _finite_number(row.get("resolved_latitude"), minimum=1.13, maximum=1.50)
        longitude = _finite_number(row.get("resolved_longitude"), minimum=103.55, maximum=104.15)
        return latitude, longitude

    def _rental_recommendations(self, profile: HousingProfile) -> dict[str, Any]:
        listings = self.service._load_live_listings()
        rent = listings.loc[listings.get("mode") == "rent"].copy()
        warnings: list[str] = []
        if rent.empty:
            return {"mode": "rent", "areas": [], "listings": [], "warnings": ["Rental snapshot is unavailable."]}
        prices = pd.to_numeric(rent.get("price_monthly"), errors="coerce")
        rent = rent.loc[prices.notna() & (prices <= float(profile.max_budget))].copy()
        rent["_price"] = pd.to_numeric(rent["price_monthly"], errors="coerce")
        if profile.rental_scope == "room":
            rent = rent.loc[rent.get("room_type").notna()].copy()
        elif profile.rental_scope == "whole_unit":
            rent = rent.loc[rent.get("room_type").isna()].copy()
        if profile.bedrooms is not None:
            warnings.append(
                "The contributed rental snapshot has no reliable bedroom-count field; the requested "
                "bedroom count is shown in the profile but was not silently enforced."
            )

        coordinates = rent[["resolved_latitude", "resolved_longitude"]].apply(
            pd.to_numeric, errors="coerce"
        )
        valid = coordinates.notna().all(axis=1)
        rent["_anchor_distance_m"] = np.nan
        if profile.anchor_latitude is not None and profile.anchor_longitude is not None and valid.any():
            rent.loc[valid, "_anchor_distance_m"] = haversine_matrix(
                coordinates.loc[valid].to_numpy(float),
                np.asarray([[profile.anchor_latitude, profile.anchor_longitude]], dtype=float),
            )[:, 0]
            if profile.max_anchor_distance_m is not None:
                distance = pd.to_numeric(rent["_anchor_distance_m"], errors="coerce")
                rent = rent.loc[
                    distance.notna() & (distance <= profile.max_anchor_distance_m)
                ].copy()
        if profile.preferred_towns:
            rent["_town_match"] = rent.get("resolved_town").isin(profile.preferred_towns)
        else:
            rent["_town_match"] = False
        if rent.empty:
            return {
                "mode": "rent",
                "areas": [],
                "listings": [],
                "warnings": warnings + ["No rental listing in the partial snapshot satisfies every hard condition."],
            }

        affordability = (1 - rent["_price"] / float(profile.max_budget)).clip(0, 1)
        score = affordability * 0.32 + rent["_town_match"].astype(float) * 0.18
        weight = pd.Series(0.50, index=rent.index)
        if profile.anchor_latitude is not None:
            distance = pd.to_numeric(rent["_anchor_distance_m"], errors="coerce")
            location_score = np.exp(-distance / 5_000).fillna(0)
            score += location_score * 0.28
            weight += 0.28
        mrt = pd.to_numeric(rent.get("nearest_mrt_distance_m"), errors="coerce")
        transit_score = (1 - mrt / 2_000).clip(0, 1).fillna(0)
        transit_weight = 0.18 if profile.transport_importance == "high" else 0.08
        score += transit_score * transit_weight
        weight += transit_weight

        regions = self._regions()
        education = rent.get("planning_area").map(
            lambda name: ((regions.get(str(name)) or {}).get("dimensions", {}).get("education", {}).get("score"))
        )
        nature = rent.get("planning_area").map(
            lambda name: ((regions.get(str(name)) or {}).get("dimensions", {}).get("nature", {}).get("score"))
        )
        if profile.school_need == "important" or profile.childcare_need == "important":
            score += pd.to_numeric(education, errors="coerce").fillna(0) / 100 * 0.12
            weight += 0.12
        if profile.park_need == "important":
            score += pd.to_numeric(nature, errors="coerce").fillna(0) / 100 * 0.10
            weight += 0.10
        rent["_advisor_score"] = score / weight
        preliminary = rent.nlargest(min(60, len(rent)), "_advisor_score").copy()

        personalised: list[tuple[float, int, dict[str, Any], dict[str, Any]]] = []
        for index, row in preliminary.iterrows():
            latitude, longitude = self._location_payload(row)
            poi = self._pois().around(latitude, longitude) if latitude is not None and longitude is not None else {}
            final_score = float(row["_advisor_score"])
            if any(
                need == "important"
                for need in (profile.school_need, profile.childcare_need, profile.healthcare_need, profile.park_need)
            ):
                final_score = final_score * 0.82 + self._need_score(profile, poi) * 0.18
            personalised.append((final_score, index, row.to_dict(), poi))
        personalised.sort(key=lambda item: (-item[0], str(item[2].get("listing_id"))))

        listing_results: list[dict[str, Any]] = []
        for final_score, _, row_dict, poi in personalised[:3]:
            row = pd.Series(row_dict)
            payload = self.service._listing_payload(row)
            reasons = [
                f"Monthly rent S${float(payload['price']):,.0f} is within the stated cap.",
            ]
            if payload.get("anchor_distance_m") is not None:
                reasons.append(
                    f"Straight-line distance to {profile.anchor_name or 'the selected place'} is "
                    f"{float(payload['anchor_distance_m']) / 1_000:.2f} km."
                )
            if payload.get("nearest_mrt_distance_m") is not None:
                reasons.append(
                    f"Recorded nearest-MRT distance is {float(payload['nearest_mrt_distance_m']):.0f} m."
                )
            reasons.extend(self._poi_reasons(profile, poi))
            payload.update(
                {
                    "advisor_score": round(final_score, 4),
                    "poi_evidence": poi,
                    "reasons": reasons,
                }
            )
            listing_results.append(payload)

        area_rows: list[dict[str, Any]] = []
        area_source = rent.copy()
        area_source["_area"] = area_source.get("subzone").fillna(
            area_source.get("planning_area")
        )
        for area_name, group in area_source.groupby("_area", dropna=True):
            first = group.nlargest(1, "_advisor_score").iloc[0]
            region = regions.get(str(first.get("planning_area"))) or {}
            area_rows.append(
                {
                    "id": f"rent:{area_name}",
                    "name": str(area_name),
                    "planning_area": first.get("planning_area"),
                    "subzone": first.get("subzone"),
                    "mode": "rent",
                    "typical_price": float(group["_price"].median()),
                    "price_unit": "per month",
                    "available_listings": int(len(group)),
                    "anchor_distance_m": (
                        float(pd.to_numeric(group["_anchor_distance_m"], errors="coerce").min())
                        if pd.to_numeric(group["_anchor_distance_m"], errors="coerce").notna().any()
                        else None
                    ),
                    "score": round(float(group["_advisor_score"].max()), 4),
                    "liveability_score": region.get("liveabilityScore"),
                    "reasons": [
                        f"{len(group)} matching listings appear in the current partial snapshot.",
                        f"Median matching rent is S${float(group['_price'].median()):,.0f} per month.",
                    ],
                }
            )
        area_rows.sort(key=lambda item: (-float(item["score"]), item["name"]))
        return {
            "mode": "rent",
            "areas": area_rows[:3],
            "listings": listing_results,
            "warnings": warnings,
            "sources": [LOCAL_SOURCE_LISTINGS, LOCAL_SOURCE_COMMUNITY, LOCAL_SOURCE_OSM],
            "disclaimer": "Periodic partial listing snapshot; availability and asking prices may have changed.",
        }

    def _buy_recommendations(self, profile: HousingProfile) -> dict[str, Any]:
        flat_type = profile.hdb_flat_type
        warnings: list[str] = []
        if flat_type is None and profile.bedrooms is not None:
            flat_type = f"{min(5, profile.bedrooms + 1)} ROOM"
            warnings.append(
                f"Interpreted {profile.bedrooms} bedrooms as HDB {flat_type}; confirm the HDB flat type before relying on it."
            )
        weights: dict[str, float] = {}
        if profile.transport_importance == "high":
            weights["transit"] = 0.28
        if profile.park_need == "important":
            weights["amenities"] = 0.16
        payload: dict[str, Any] = {
            "budget": profile.max_budget,
            "top_k": 20,
            "use_llm": False,
        }
        if flat_type:
            payload["flat_types"] = [flat_type]
        if profile.preferred_towns:
            payload["preferred_towns"] = profile.preferred_towns
        if profile.min_floor_area_sqm is not None:
            payload["min_floor_area_sqm"] = profile.min_floor_area_sqm
        if weights:
            payload["weights"] = weights
        if profile.anchor_latitude is not None and profile.anchor_longitude is not None:
            payload.update(
                {
                    "anchor_name": profile.anchor_name,
                    "anchor_latitude": profile.anchor_latitude,
                    "anchor_longitude": profile.anchor_longitude,
                }
            )
            if profile.max_anchor_distance_m is not None:
                payload["max_anchor_distance_m"] = profile.max_anchor_distance_m
        ranked = self.service.get_recommendations(payload)
        candidates = ranked.get("recommendations") or []
        personalised: list[tuple[float, dict[str, Any]]] = []
        for item in candidates:
            latitude = item.get("latitude")
            longitude = item.get("longitude")
            poi = self._pois().around(float(latitude), float(longitude)) if latitude is not None and longitude is not None else {}
            score = float(item.get("ranking_score") or 0)
            if any(
                need == "important"
                for need in (profile.school_need, profile.childcare_need, profile.healthcare_need, profile.park_need)
            ):
                score = score * 0.82 + self._need_score(profile, poi) * 0.18
            item = {**item, "advisor_score": round(score, 4), "poi_evidence": poi}
            item["reasons"] = list(item.get("reasons") or []) + self._poi_reasons(profile, poi)
            personalised.append((score, item))
        personalised.sort(key=lambda pair: (-pair[0], pair[1]["candidate_id"]))
        top_candidates = [item for _, item in personalised[:3]]
        areas: list[dict[str, Any]] = []
        for item in top_candidates:
            region = None
            if item.get("latitude") is not None and item.get("longitude") is not None:
                region = self.service._locations().index.locate(
                    float(item["latitude"]), float(item["longitude"])
                )
            areas.append(
                {
                    "id": item["candidate_id"],
                    "name": item["block_address"],
                    "planning_area": item["town"],
                    "subzone": (region or {}).get("subzone"),
                    "mode": "buy",
                    "typical_price": item["median_resale_price"],
                    "price_unit": "historical resale median",
                    "available_listings": None,
                    "anchor_distance_m": item.get("anchor_distance_m"),
                    "score": item["advisor_score"],
                    "reasons": item.get("reasons", [])[:5],
                    "poi_evidence": item.get("poi_evidence"),
                }
            )
        listings: list[dict[str, Any]] = []
        for item in (ranked.get("live_listings") or [])[:3]:
            poi = {}
            if item.get("latitude") is not None and item.get("longitude") is not None:
                poi = self._pois().around(float(item["latitude"]), float(item["longitude"]))
            reasons = [f"Asking price S${float(item['price']):,.0f} is within the stated cap."]
            if item.get("anchor_distance_m") is not None:
                reasons.append(
                    f"Straight-line distance to {profile.anchor_name or 'the selected place'} is "
                    f"{float(item['anchor_distance_m']) / 1_000:.2f} km."
                )
            reasons.extend(self._poi_reasons(profile, poi))
            listings.append({**item, "poi_evidence": poi, "reasons": reasons})
        return {
            "mode": "buy",
            "areas": areas,
            "listings": listings,
            "warnings": warnings + list(ranked.get("warnings") or []),
            "sources": [LOCAL_SOURCE_HDB, LOCAL_SOURCE_LISTINGS, LOCAL_SOURCE_OSM],
            "disclaimer": ranked.get("disclaimer"),
        }

    def recommendations(self, profile: HousingProfile) -> dict[str, Any]:
        if profile.max_budget is None:
            raise ValueError("maximum budget is required before recommendation")
        if profile.housing_mode == "rent":
            return self._rental_recommendations(profile)
        if profile.housing_mode == "buy":
            return self._buy_recommendations(profile)
        raise ValueError("choose rent or buy before recommendation")

    def _confirm_location(self, session: AdvisorSession, candidate_id: str) -> dict[str, Any]:
        candidate = next(
            (item for item in session.pending_locations if item.get("id") == candidate_id),
            None,
        )
        if candidate is None:
            raise ValueError("location candidate is no longer available; search again")
        region = self.service._locations().index.locate(
            float(candidate["latitude"]), float(candidate["longitude"])
        )
        if region is None:
            raise ValueError("confirmed location must be inside Singapore")
        profile = session.profile
        profile.anchor_name = str(candidate["name"])
        profile.anchor_address = str(candidate["address"])
        profile.anchor_latitude = float(candidate["latitude"])
        profile.anchor_longitude = float(candidate["longitude"])
        profile.anchor_planning_area = region["planning_area"]
        profile.anchor_subzone = region["subzone"]
        profile.location_query = profile.location_query or profile.anchor_name
        session.pending_locations = []
        return candidate

    def message(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("advisor payload must be an object")
        session_id = payload.get("session_id")
        if session_id is not None and not isinstance(session_id, str):
            raise ValueError("session_id must be text")
        session = self.sessions.get(session_id)
        message = str(payload.get("message") or "").strip()
        if len(message) > 4_000:
            raise ValueError("advisor message must be at most 4,000 characters")
        candidate_id = payload.get("confirmed_location_id")
        if candidate_id is not None and not isinstance(candidate_id, str):
            raise ValueError("confirmed_location_id must be text")
        if not message and not candidate_id:
            raise ValueError("provide a message or confirmed_location_id")

        with session.lock:
            sources: list[dict[str, str]] = []
            method = "rules"
            web_warning = None
            recommendation_requested = False
            if candidate_id:
                previous_user_message = next(
                    (
                        turn["content"]
                        for turn in reversed(session.turns)
                        if turn.get("role") == "user"
                    ),
                    "",
                )
                candidate = self._confirm_location(session, candidate_id)
                chinese = session.profile.language != "en"
                answer = (
                    f"已确认地点：{candidate['name']}（{candidate['address']}）。后续距离都按直线距离计算。"
                    if chinese else
                    f"Location confirmed: {candidate['name']} ({candidate['address']}). Subsequent distances are straight-line distances."
                )
                sources.append(
                    {"kind": "local", "title": "OneMap confirmed Singapore location", "url": "https://www.onemap.gov.sg/"}
                )
                if re.search(r"多少|价格|租金|房价|price|rent|cost", previous_user_message, re.I):
                    evidence = self._local_evidence(previous_user_message, session.profile)
                    snapshot = evidence.get("snapshot") or {}
                    radius_km = float(snapshot.get("anchor_radius_m") or 5_000) / 1_000
                    if session.profile.housing_mode == "rent" and snapshot.get("nearby_median_monthly_rent") is not None:
                        value = float(snapshot["nearby_median_monthly_rent"])
                        count = int(snapshot.get("nearby_rental_count") or 0)
                        answer += (
                            f" 项目定期快照中，该点直线 {radius_km:g} 公里内有 {count:,} 条可定价租房记录，月租中位数约 S${value:,.0f}；这不是完整实时市场。"
                            if chinese else
                            f" In the periodic project snapshot, {count:,} priced rentals within {radius_km:g} km have a median monthly rent of about S${value:,.0f}; this is not complete live inventory."
                        )
                        sources.extend(evidence.get("sources") or [])
                    elif session.profile.housing_mode == "buy" and snapshot.get("nearby_median_sale_asking_price") is not None:
                        value = float(snapshot["nearby_median_sale_asking_price"])
                        count = int(snapshot.get("nearby_sale_count") or 0)
                        answer += (
                            f" 项目定期快照中，该点直线 {radius_km:g} 公里内有 {count:,} 条可定价买房挂牌，挂牌价中位数约 S${value:,.0f}；这不是成交估值或完整实时市场。"
                            if chinese else
                            f" In the periodic project snapshot, {count:,} priced sale listings within {radius_km:g} km have a median asking price of about S${value:,.0f}; this is neither a valuation nor complete live inventory."
                        )
                        sources.extend(evidence.get("sources") or [])
                session.add_turn("user", f"Confirmed OneMap location: {candidate['name']}")
            else:
                rule_updates, rule_recommendation = _rule_profile_updates(message, session.profile)
                evidence = self._local_evidence(message, session.profile)
                sources.extend(evidence.get("sources") or [])
                model_result: dict[str, Any] | None = None
                if self.client.available:
                    try:
                        model_result = self.client.respond(
                            message, session.profile, session.turns, evidence
                        )
                    except (requests.RequestException, ValueError, json.JSONDecodeError):
                        model_result = None
                updates = dict(rule_updates)
                if model_result:
                    for key, value in (model_result.get("profile_updates") or {}).items():
                        if value not in (None, "", []):
                            updates[key] = value
                    answer = _clean_text(model_result.get("answer"), maximum=4_000) or self._fallback_answer(message, evidence)
                    recommendation_requested = bool(model_result.get("recommendation_requested"))
                    sources.extend(model_result.get("sources") or [])
                    method = str(model_result.get("method") or "openai")
                    if model_result.get("web_search_unavailable"):
                        web_warning = "The configured API relay did not support web search for this turn; local evidence was used."
                else:
                    answer = self._fallback_answer(message, evidence)
                if (
                    updates.get("school_need") == "important"
                    and session.profile.school_need != "important"
                    and not _child_school_need_explicit(message)
                ):
                    updates.pop("school_need", None)
                recommendation_requested = recommendation_requested or rule_recommendation
                old_location_query = session.profile.location_query
                session.profile.merge(updates)
                if (
                    old_location_query
                    and session.profile.location_query
                    and old_location_query.casefold() != session.profile.location_query.casefold()
                ):
                    session.pending_locations = []
                if (
                    session.profile.institution
                    and not session.profile.location_query
                    and not session.profile.has_location
                ):
                    session.profile.location_query = session.profile.institution
                    session.profile.location_reason = "inferred_from_institution"
                session.add_turn("user", message)

            profile = session.profile
            chinese = profile.language != "en" if profile.language else _contains_cjk(message)
            if (
                profile.location_query
                and profile.anchor_latitude is None
                and not session.pending_locations
            ):
                try:
                    session.pending_locations = self.service.search_locations(
                        profile.location_query, limit=5
                    )["candidates"]
                except DataUnavailableError:
                    session.pending_locations = []
                    web_warning = web_warning or "OneMap is unavailable; the exact location is not confirmed yet."

            progress = self._profile_progress(profile)
            recommendation_result = None
            if session.pending_locations:
                follow_up = (
                    "为了避免把地点定位错，请先从下面的 OneMap 结果中确认一个地点。"
                    if chinese else
                    "To avoid locating you incorrectly, please confirm one of the OneMap results below."
                )
            elif recommendation_requested and progress["ready"]:
                recommendation_result = self.recommendations(profile)
                follow_up = (
                    "我已按硬条件筛选并生成三处地点和三条真实房源；你可以继续告诉我想调整的条件。"
                    if chinese else
                    "I applied the hard constraints and generated three locations and three real listings. Tell me what you would like to adjust."
                )
                sources.extend(recommendation_result.get("sources") or [])
            else:
                follow_up = self._next_question(profile, progress, chinese=chinese)
                if recommendation_requested and not progress["ready"]:
                    prefix = "在可靠推荐前，我还缺少一项关键信息。" if chinese else (
                        "I still need one key detail before I can make a reliable recommendation."
                    )
                    follow_up = f"{prefix} {follow_up}"
            reply = f"{answer}\n\n{follow_up}".strip()
            session.add_turn("assistant", reply)
            return {
                "session_id": session.session_id,
                "reply": reply,
                "profile": profile.public(),
                "progress": progress,
                "location_candidates": session.pending_locations,
                "recommendations": recommendation_result,
                "sources": _dedupe_sources(sources),
                "warnings": [web_warning] if web_warning else [],
                "method": method,
                "privacy": (
                    "Profile and the latest 12 turns stay only in this server process for up to "
                    "four hours. They are not written to project files and disappear on reset or restart."
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
                "profile": session.profile.public(),
                "progress": self._profile_progress(session.profile),
                "turns": list(session.turns),
                "location_candidates": list(session.pending_locations),
                "privacy": (
                    "Profile and the latest 12 turns stay only in this server process for up to "
                    "four hours. They are not written to project files and disappear on reset or restart."
                ),
            }
