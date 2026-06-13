"""餐厅排序：菜系偏好 + 餐饮预算。"""

from __future__ import annotations

from typing import Any

from src.data_layer.schema import Constraints, GroundedPreferences, POICandidate


def rank_restaurants(
    restaurants: list[dict[str, Any]],
    preferences: GroundedPreferences,
    constraints: Constraints | None = None,
    top_k: int = 30,
) -> list[POICandidate]:
    """按菜系偏好、人均价格、餐饮预算排序餐厅。

    Args:
        restaurants: 原始餐厅列表。
        preferences: 偏好权重（cuisine_weights）。
        constraints: 可选，用于读取餐饮预算上限。
        top_k: 保留数量。

    Returns:
        list[POICandidate]: 排序后餐厅候选。
    """
    if not restaurants:
        return []

    dining_budget = None
    if constraints:
        for card in constraints.cards:
            if card.category == "budget" and card.parameters.get("budget_type") == "dining":
                val = card.parameters.get("max_cost")
                if val is not None:
                    dining_budget = float(val)

    scored: list[tuple[float, dict[str, Any]]] = []
    for rest in restaurants:
        price = _float_price(rest)
        score = 1.0

        # 菜系偏好匹配
        name = str(rest.get("name", ""))
        cuisine = str(rest.get("cuisine", rest.get("type", "")))
        for tag, weight in preferences.cuisine_weights.items():
            if tag.lower() in name.lower() or tag.lower() in cuisine.lower():
                score += float(weight)

        # 本地特色加分
        if preferences.tags.get("cuisine_preference") == "local":
            if any(kw in name for kw in ("本地", "特色", "老字号")):
                score += 0.5

        # 人均价格：预算紧张时偏好低价，预算宽松时可接受高价
        if dining_budget is not None and dining_budget > 0:
            # 假设每天 3 餐，估算人均单餐预算
            days = (constraints.global_params.get("days") if constraints else None) or 3
            people = (constraints.global_params.get("people_number") if constraints else None) or 1
            per_meal_budget = dining_budget / (days * people * 3)
            if price <= per_meal_budget:
                score += 1.0
            elif price <= per_meal_budget * 1.5:
                score += 0.3
            else:
                score -= 0.5

        rating = rest.get("rating")
        if rating is not None:
            try:
                score += float(rating) * 0.3
            except (TypeError, ValueError):
                pass

        scored.append((score, rest))

    scored.sort(key=lambda x: -x[0])
    result: list[POICandidate] = []
    for score, rest in scored[:top_k]:
        result.append(
            POICandidate(
                poi_id=_rest_id(rest),
                name=str(rest.get("name", "")),
                score=round(score, 4),
                region=str(rest.get("region", "")),
                metadata=dict(rest),
            )
        )
    return result


def _rest_id(rest: dict[str, Any]) -> str:
    for key in ("id", "poi_id", "uid", "name"):
        if rest.get(key):
            return str(rest[key])
    return "unknown"


def _float_price(record: dict[str, Any]) -> float:
    for key in ("price", "avg_price", "cost", "per_capita"):
        if record.get(key) is not None:
            try:
                return float(record[key])
            except (TypeError, ValueError):
                pass
    return 50.0  # 无价格时用默认值
