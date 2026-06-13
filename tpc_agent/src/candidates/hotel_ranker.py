"""酒店排序：预算 + 位置锚点 + 类型约束。"""

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
    """按预算、锚点距离、酒店类型要求排序酒店。

    Args:
        hotels: 原始酒店列表。
        constraints: 约束集合（读取 budget/accommodation/spatial 卡片）。
        top_k: 保留数量。
        anchor_pois: 空间锚点 POI 列表（来自 active_info）。

    Returns:
        list[POICandidate]: 排序后酒店候选。
    """
    if not hotels:
        return []

    budget_limit = _get_budget_limit(constraints, "accommodation")
    required_type = _get_required_hotel_type(constraints)
    max_dist = _get_max_anchor_distance(constraints)
    anchor = _pick_primary_anchor(anchor_pois)

    scored: list[tuple[float, dict[str, Any]]] = []
    for hotel in hotels:
        price = _float_price(hotel)
        # 硬过滤：超出住宿预算的直接跳过
        if budget_limit is not None and price > budget_limit:
            continue
        # 硬过滤：酒店类型不匹配
        if required_type and not _hotel_has_type(hotel, required_type):
            continue

        score = 1.0
        # 价格越接近预算中位越优（避免过贵或过差）
        if budget_limit is not None and budget_limit > 0:
            ratio = price / budget_limit
            score += max(0, 1.0 - abs(ratio - 0.6))

        # 距锚点越近越好
        if anchor and max_dist is not None:
            dist = _estimate_distance(hotel, anchor)
            if dist <= max_dist:
                score += (1.0 - dist / max(max_dist, 0.1)) * 2.0
            else:
                score -= 1.0  # 超出距离要求扣分

        rating = hotel.get("rating")
        if rating is not None:
            try:
                score += float(rating) * 0.3
            except (TypeError, ValueError):
                pass

        scored.append((score, hotel))

    scored.sort(key=lambda x: -x[0])
    result: list[POICandidate] = []
    for score, hotel in scored[:top_k]:
        result.append(
            POICandidate(
                poi_id=_hotel_id(hotel),
                name=str(hotel.get("name", "")),
                score=round(score, 4),
                region=str(hotel.get("region", "")),
                metadata=dict(hotel),
            )
        )
    return result


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
    return 0.0


def _get_budget_limit(constraints: Constraints, budget_type: str) -> float | None:
    for card in constraints.cards:
        if card.category == "budget" and card.parameters.get("budget_type") == budget_type:
            val = card.parameters.get("max_cost")
            if val is not None:
                return float(val)
    return None


def _get_required_hotel_type(constraints: Constraints) -> str | None:
    for card in constraints.cards:
        if card.category == "accommodation":
            return card.parameters.get("required_type")
    return None


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
        if ap.get("resolved", True) and (ap.get("latitude") or ap.get("lat")):
            return ap
    return anchor_pois[0]


def _hotel_has_type(hotel: dict[str, Any], required: str) -> bool:
    """检查酒店是否满足类型要求（如 Free parking）。"""
    req = required.lower()
    for key in ("types", "tags", "features", "amenities"):
        val = hotel.get(key)
        if isinstance(val, list):
            if any(req in str(v).lower() for v in val):
                return True
        elif isinstance(val, str) and req in val.lower():
            return True
    # 名称中包含类型关键词也算匹配
    return req in str(hotel.get("name", "")).lower()


def _estimate_distance(a: dict[str, Any], b: dict[str, Any]) -> float:
    """估算两 POI 间距离（km）。"""
    def coords(rec: dict) -> tuple[float, float] | None:
        if "latitude" in rec and "longitude" in rec:
            return float(rec["latitude"]), float(rec["longitude"])
        if "lat" in rec and "lng" in rec:
            return float(rec["lat"]), float(rec["lng"])
        return None

    ca, cb = coords(a), coords(b)
    if ca and cb:
        r = 6371.0
        phi1, phi2 = math.radians(ca[0]), math.radians(cb[0])
        dphi = math.radians(cb[0] - ca[0])
        dlambda = math.radians(cb[1] - ca[1])
        x = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        return 2 * r * math.asin(math.sqrt(x))
    return 999.0
