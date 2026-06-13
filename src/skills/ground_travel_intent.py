"""Ground natural-language travel intent into planner parameters."""

from __future__ import annotations

import re
from typing import Any

from src.data_layer.schema import Constraints
from src.skills.skill_types import SkillContext, SkillResult


def ground_travel_intent(
    payload: dict[str, Any],
    context: SkillContext | None = None,
) -> SkillResult:
    """Infer local planning hints from constraints and raw text.

    This skill is intentionally offline and rule-based.  It complements the
    constraint cards by turning fuzzy phrases into bounded planner parameters.
    """
    constraints = payload.get("constraints") or (context.constraints if context else None)
    text = str(payload.get("nl_text") or _constraints_text(constraints)).lower()
    cards = getattr(constraints, "cards", []) or []

    hints: dict[str, Any] = {
        "pace": "balanced",
        "max_pois_per_day": None,
        "buffer_minutes": 20,
        "prefer_metro": None,
        "budget_mode": False,
        "avoid_types": [],
        "required_types": [],
        "must_visit": [],
    }
    poi_weights: dict[str, float] = {}
    tags: dict[str, Any] = {}
    evidence: list[str] = []

    if any(k in text for k in ("not too tired", "relaxed", "easy", "轻松", "不要太累", "不太累")):
        hints.update({"pace": "relaxed", "max_pois_per_day": 2, "buffer_minutes": 35})
        evidence.append("relaxed pace phrase")
    if any(k in text for k in ("as many as possible", "尽可能多", "多玩", "多去")):
        hints.update({"pace": "intensive", "max_pois_per_day": 4, "buffer_minutes": 15})
        evidence.append("intensive pace phrase")
    if any(k in text for k in ("budget", "cheap", "省钱", "便宜", "低价")):
        hints["budget_mode"] = True
        evidence.append("budget phrase")
    if any(k in text for k in ("metro", "subway", "地铁")):
        hints["prefer_metro"] = True
        evidence.append("metro preference")
    if any(k in text for k in ("taxi", "打车", "出租车")):
        hints["prefer_metro"] = False
        evidence.append("taxi preference")

    forbidden = _extract_forbidden_types(text)
    required = _extract_required_types(text)
    if forbidden:
        hints["avoid_types"] = sorted(forbidden)
        evidence.append("forbidden attraction types")
    if required:
        hints["required_types"] = sorted(required)
        for value in required:
            poi_weights[value] = max(poi_weights.get(value, 0.0), 2.0)
        evidence.append("required attraction types")

    hotel_anchor = _extract_hotel_anchor(text)
    if hotel_anchor:
        hints["hotel_anchor"] = hotel_anchor["anchor"]
        hints["hotel_max_distance_km"] = hotel_anchor["max_distance_km"]
        tags["hotel_anchor"] = hotel_anchor
        evidence.append("hotel distance anchor")

    for card in cards:
        params = getattr(card, "parameters", {}) or {}
        if params.get("must_visit_poi"):
            name = str(params["must_visit_poi"])
            hints["must_visit"].append(name)
            poi_weights[name] = max(poi_weights.get(name, 0.0), 3.0)
        if params.get("must_visit_type"):
            value = str(params["must_visit_type"])
            if value not in hints["required_types"]:
                hints["required_types"].append(value)
            poi_weights[value] = max(poi_weights.get(value, 0.0), 2.0)
        if params.get("forbidden_attraction_type"):
            value = str(params["forbidden_attraction_type"])
            if value not in hints["avoid_types"]:
                hints["avoid_types"].append(value)
        if getattr(card, "category", "") == "budget":
            hints["budget_mode"] = True

    return SkillResult(
        name="ground_travel_intent",
        category="semantic",
        decision={
            "planning_hints": hints,
            "poi_weights": poi_weights,
            "tags": tags,
        },
        score=float(len(evidence)),
        evidence=evidence,
    )


def _constraints_text(constraints: Constraints | None) -> str:
    if constraints is None:
        return ""
    gp = constraints.global_params or {}
    parts = [str(gp.get("nature_language") or "")]
    for card in constraints.cards or []:
        parts.append(str(card.description))
    return " ".join(parts)


def _extract_forbidden_types(text: str) -> set[str]:
    values: set[str] = set()
    patterns = (
        r"(?:do not|don't|avoid|不去|不要去|禁止).*?(museum|memorial hall|park|temple|zoo|gallery)",
        r"(museum|memorial hall|博物馆|纪念馆|公园|寺|动物园).*?(?:do not|avoid|不去|不要去|禁止)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            values.add(_normalize_type(match.group(1)))
    return values


def _extract_required_types(text: str) -> set[str]:
    values: set[str] = set()
    patterns = (
        r"(?:want|like|visit|想去|要去|希望去).*?(park|museum|memorial hall|temple|zoo|gallery|公园|博物馆|纪念馆)",
        r"(park|museum|memorial hall|temple|zoo|gallery|公园|博物馆|纪念馆).*?(?:want|like|visit|想去|要去|希望)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            values.add(_normalize_type(match.group(1)))
    return values


def _normalize_type(value: str) -> str:
    mapping = {
        "博物馆": "museum",
        "纪念馆": "memorial hall",
        "公园": "park",
        "寺": "temple",
        "动物园": "zoo",
    }
    return mapping.get(value.lower(), value.lower())


def _extract_hotel_anchor(text: str) -> dict[str, Any] | None:
    patterns = (
        r"hotel\s+within\s+(\d+(?:\.\d+)?)\s*km\s+of\s+([a-z0-9 .'\-]+)",
        r"酒店.*?([0-9]+(?:\.[0-9]+)?)\s*公里.*?(?:内|以内).*?(?:离|距|靠近|附近)?\s*([\u4e00-\u9fffA-Za-z0-9 .'\-]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            dist = float(match.group(1))
            anchor = match.group(2).strip(" .,，。")
            if anchor:
                return {"anchor": anchor, "max_distance_km": dist}
    return None
