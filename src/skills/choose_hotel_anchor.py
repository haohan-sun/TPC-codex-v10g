"""Choose a hotel anchor as a local scheduling skill."""

from __future__ import annotations

import math
from typing import Any

from src.data_layer.schema import CandidatePool, Plan, POICandidate
from src.skills.skill_types import SkillContext, SkillResult


def choose_hotel_anchor_skill(
    payload: dict[str, Any],
    context: SkillContext | None = None,
) -> SkillResult:
    hotels = list(payload.get("hotels") or getattr(context.candidates, "hotels", []) if context else payload.get("hotels") or [])
    pois = list(payload.get("pois") or getattr(context.candidates, "pois", []) if context else payload.get("pois") or [])
    pc = payload.get("planning_constraints") or payload.get("constraints") or (context.constraints if context else None)
    policy = payload.get("policy") or (context.policy if context else "safe")
    sandbox = payload.get("sandbox") or (context.sandbox if context else None)
    anchor = payload.get("anchor") or getattr(pc, "hotel_near_anchor", None)
    max_dist = payload.get("max_distance_km") or getattr(pc, "hotel_max_distance_km", None)

    if not hotels:
        return SkillResult(
            name="choose_hotel_anchor",
            category="schedule",
            warnings=["no hotel candidates"],
        )

    scored: list[tuple[float, POICandidate, list[str]]] = []
    for hotel in hotels:
        reasons: list[str] = []
        price = _price(hotel, 300.0)
        score = 10.0

        if policy == "budget" or getattr(pc, "accommodation_budget", None) is not None:
            score += max(0.0, 5.0 - price / 120.0)
            reasons.append("budget-sensitive price")
        else:
            score += max(0.0, 3.0 - price / 250.0)

        required_type = getattr(pc, "required_hotel_type", None)
        if required_type:
            if _has_hotel_type(hotel, required_type):
                score += 4.0
                reasons.append("required hotel type")
            else:
                score -= 5.0

        dist = _anchor_distance(hotel, anchor, pois, sandbox, getattr(pc, "target_city", ""))
        if dist is not None:
            if max_dist is not None:
                if dist <= float(max_dist):
                    score += 6.0 * (1.0 - dist / max(float(max_dist), 0.1))
                    reasons.append("within anchor distance")
                else:
                    score -= min(8.0, dist - float(max_dist))
            elif policy == "low_transport":
                score += max(0.0, 4.0 - dist)
                reasons.append("low transport anchor")

        score += float(getattr(hotel, "score", 0.0) or 0.0) * 0.2
        scored.append((score, hotel, reasons))

    scored.sort(key=lambda item: (-item[0], _price(item[1], 9999.0), item[1].name))
    best_score, best, reasons = scored[0]
    return SkillResult(
        name="choose_hotel_anchor",
        category="schedule",
        decision={
            "hotel_id": best.poi_id,
            "hotel_name": best.name,
            "anchor": anchor,
            "score": round(best_score, 4),
            "reason": "; ".join(reasons) if reasons else "best ranked hotel candidate",
        },
        score=best_score,
        evidence=[best.name],
    )


def choose_hotel_anchor_candidate(
    hotels: list[POICandidate],
    pc: Any,
    pois: list[POICandidate] | None = None,
    *,
    policy: str = "safe",
    sandbox: Any | None = None,
) -> SkillResult:
    """Convenience helper for planner call sites."""
    return choose_hotel_anchor_skill(
        {
            "hotels": hotels,
            "pois": pois or [],
            "planning_constraints": pc,
            "policy": policy,
            "sandbox": sandbox,
        },
        SkillContext(policy=policy, sandbox=sandbox),
    )


def choose_hotel_anchor(plan: Plan, candidates: CandidatePool) -> Plan:
    """Compatibility wrapper: annotate an internal plan with a hotel decision."""
    result = choose_hotel_anchor_skill(
        {"hotels": candidates.hotels, "pois": candidates.pois},
        SkillContext(candidates=candidates, policy=plan.policy),
    )
    plan.metadata["skill_choose_hotel_anchor"] = result.decision
    return plan


def _price(item: POICandidate, default: float) -> float:
    for key in ("price", "cost", "avg_price", "night_price"):
        value = (item.metadata or {}).get(key)
        if value not in (None, ""):
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
    return default


def _has_hotel_type(hotel: POICandidate, required: str) -> bool:
    req = required.lower()
    meta = hotel.metadata or {}
    haystack = " ".join(str(meta.get(k, "")) for k in (
        "featurehoteltype",
        "featureHotelType",
        "features",
        "amenities",
        "tags",
        "type",
        "name",
    )).lower()
    return req in haystack or req in hotel.name.lower()


def _anchor_distance(
    hotel: POICandidate,
    anchor: str | None,
    pois: list[POICandidate],
    sandbox: Any | None,
    city: str,
) -> float | None:
    if anchor:
        if sandbox is not None and city:
            try:
                value = sandbox.poi_distance(city, hotel.name, anchor, "09:00", "metro")
                if value is not None:
                    return float(value)
            except Exception:
                pass
        anchor_poi = _find_by_name(pois, anchor)
        if anchor_poi is not None:
            return _candidate_distance(hotel, anchor_poi)
    if pois:
        distances = [_candidate_distance(hotel, p) for p in pois[:8]]
        distances = [d for d in distances if d is not None]
        if distances:
            return sum(distances) / len(distances)
    return None


def _find_by_name(items: list[POICandidate], name: str) -> POICandidate | None:
    needle = name.lower()
    for item in items:
        if needle in item.name.lower() or needle == item.poi_id.lower():
            return item
    return None


def _candidate_distance(a: POICandidate, b: POICandidate) -> float | None:
    ca, cb = _coords(a.metadata or {}), _coords(b.metadata or {})
    if not ca or not cb:
        return None
    r = 6371.0
    phi1, phi2 = math.radians(ca[0]), math.radians(cb[0])
    dphi = math.radians(cb[0] - ca[0])
    dlambda = math.radians(cb[1] - ca[1])
    x = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(x))


def _coords(rec: dict[str, Any]) -> tuple[float, float] | None:
    try:
        if "latitude" in rec and "longitude" in rec:
            return float(rec["latitude"]), float(rec["longitude"])
        if "lat" in rec and "lon" in rec:
            return float(rec["lat"]), float(rec["lon"])
        if "lat" in rec and "lng" in rec:
            return float(rec["lat"]), float(rec["lng"])
    except (TypeError, ValueError):
        return None
    return None
