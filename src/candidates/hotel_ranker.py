"""Hotel ranking with budget, anchor distance, and feature constraints."""

from __future__ import annotations

import math
from typing import Any

from src.data_layer.schema import Constraints, POICandidate


def rank_hotels(
    hotels: list[dict[str, Any]],
    constraints: Constraints,
    top_k: int = 10,
    anchor_pois: list[dict[str, Any]] | None = None,
) -> list[POICandidate]:
    if not hotels:
        return []

    budget_limit = _get_budget_limit(constraints, "accommodation")
    required_type = _get_required_hotel_type(constraints)
    required_names = _get_required_hotel_names(constraints)
    max_dist = _get_max_anchor_distance(constraints)
    anchor = _pick_primary_anchor(anchor_pois)
    people = int(constraints.global_params.get("people_number") or 1)
    days = int(constraints.global_params.get("days") or 1)
    rooms = max(1, (people + 1) // 2)
    nights = max(1, days - 1)

    scored: list[tuple[float, dict[str, Any]]] = []
    for hotel in hotels:
        price = _float_price(hotel)
        stay_cost = price * rooms * nights

        if budget_limit is not None and stay_cost > budget_limit:
            continue
        if required_type and not _hotel_has_type(hotel, required_type):
            continue

        score = 1.0
        if required_names and _hotel_matches_name(hotel, required_names):
            score += 1000.0

        if budget_limit is not None and budget_limit > 0:
            ratio = stay_cost / budget_limit
            score += max(0.0, 1.0 - abs(ratio - 0.55))
        else:
            score += max(0.0, 1.0 - price / 1000.0)

        if anchor and max_dist is not None:
            dist = _estimate_distance(hotel, anchor)
            if dist <= max_dist:
                score += (1.0 - dist / max(max_dist, 0.1)) * 2.0
            else:
                score -= 3.0

        rating = hotel.get("rating") or hotel.get("score")
        if rating is not None:
            try:
                score += float(rating) * 0.3
            except (TypeError, ValueError):
                pass

        scored.append((score, hotel))

    scored.sort(key=lambda x: (-x[0], _float_price(x[1])))
    return [
        POICandidate(
            poi_id=_hotel_id(hotel),
            name=str(hotel.get("name", "")),
            score=round(score, 4),
            region=str(hotel.get("region", hotel.get("district", ""))),
            metadata=dict(hotel),
        )
        for score, hotel in scored[:top_k]
    ]


def _hotel_id(hotel: dict[str, Any]) -> str:
    for key in ("id", "poi_id", "uid", "name"):
        if hotel.get(key):
            return str(hotel[key])
    return "unknown"


def _float_price(record: dict[str, Any]) -> float:
    for key in ("price", "cost", "avg_price", "night_price"):
        if record.get(key) is not None:
            try:
                return float(record[key])
            except (TypeError, ValueError):
                pass
    return 300.0


def _get_budget_limit(constraints: Constraints, budget_type: str) -> float | None:
    for card in constraints.cards:
        if card.category == "budget" and card.parameters.get("budget_type") == budget_type:
            val = card.parameters.get("max_cost")
            if val is not None:
                return float(val)
    return None


def _get_required_hotel_type(constraints: Constraints) -> str | None:
    for card in constraints.cards:
        if card.category == "accommodation" and card.parameters.get("required_type"):
            return str(card.parameters["required_type"])
    return None


def _get_required_hotel_names(constraints: Constraints) -> list[str]:
    names: list[str] = []
    for card in constraints.cards:
        if card.category == "accommodation" and card.parameters.get("required_name"):
            names.append(str(card.parameters["required_name"]))
    return names


def _get_max_anchor_distance(constraints: Constraints) -> float | None:
    for card in constraints.cards:
        if card.category == "spatial" and card.parameters.get("anchor_poi"):
            val = card.parameters.get("max_distance_km")
            if val is not None:
                return float(val)
    return None


def _pick_primary_anchor(anchor_pois: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    if not anchor_pois:
        return None
    for ap in anchor_pois:
        if ap.get("resolved", True) and _coords(ap):
            return ap
    return anchor_pois[0]


def _hotel_has_type(hotel: dict[str, Any], required: str) -> bool:
    req = required.lower()
    for key in ("types", "tags", "features", "amenities", "featurehoteltype", "featureHotelType"):
        val = hotel.get(key)
        if isinstance(val, list) and any(req in str(v).lower() for v in val):
            return True
        if isinstance(val, str) and req in val.lower():
            return True
    return req in str(hotel.get("name", "")).lower()


def _hotel_matches_name(hotel: dict[str, Any], names: list[str]) -> bool:
    hotel_name = str(hotel.get("name", ""))
    hotel_norm = _norm_text(hotel_name)
    return any(name.lower() in hotel_name.lower() or _norm_text(name) == hotel_norm for name in names)


def _norm_text(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


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


def _estimate_distance(a: dict[str, Any], b: dict[str, Any]) -> float:
    ca, cb = _coords(a), _coords(b)
    if ca and cb:
        r = 6371.0
        phi1, phi2 = math.radians(ca[0]), math.radians(cb[0])
        dphi = math.radians(cb[0] - ca[0])
        dlambda = math.radians(cb[1] - ca[1])
        x = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        return 2 * r * math.asin(math.sqrt(x))
    return 999.0
