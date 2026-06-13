"""语义落地与偏好权重。"""

from __future__ import annotations

from src.data_layer.schema import ActiveInfo, Constraints, GroundedPreferences
from src.semantic.cuisine_mapper import map_cuisine_preferences
from src.semantic.pace_mapper import map_pace
from src.semantic.preference_mapper import map_preferences


def semantic_grounding(
    constraints: Constraints,
    active_info: ActiveInfo,
) -> GroundedPreferences:
    """将模糊偏好落地为可计算的权重向量。

    输入来源：
        - constraints 卡片（必去、预算、节奏等）
        - active_info 中已拉取的 POI/锚点数据
        - nature_language 文本

    Args:
        constraints: 约束集合。
        active_info: 主动查询结果。

    Returns:
        GroundedPreferences: 偏好权重，供 candidate/planner 使用。
    """
    gp = constraints.global_params
    nl_text = gp.get("nature_language") or ""

    poi_weights = map_preferences(constraints)

    # 从 active_info 中提升已解析 POI/锚点权重
    for poi in active_info.fetched_data.get("pois") or []:
        name = str(poi.get("name", ""))
        if name:
            poi_weights[name] = max(poi_weights.get(name, 0), 1.0)

    for anchor in active_info.fetched_data.get("anchor_pois") or []:
        name = str(anchor.get("name", ""))
        if name:
            poi_weights[name] = max(poi_weights.get(name, 0), 2.5)

    for item in active_info.fetched_data.get("must_visit_resolved") or []:
        poi = item.get("poi") or {}
        name = str(poi.get("name", item.get("query_name", "")))
        if name:
            poi_weights[name] = 3.0

    cuisine_weights = map_cuisine_preferences(constraints, nl_text)
    pace_weight = map_pace(constraints, nl_text)

    # 预算约束 → 提高 budget_weight
    budget_weight = 0.5
    for card in constraints.cards:
        if card.category == "budget":
            budget_weight = 0.85

    # 交通约束 → transport_weight
    transport_weight = 0.5
    for card in constraints.cards:
        if card.category == "transport":
            transport_weight = 0.75

    tags: dict = {}
    if "local" in cuisine_weights:
        tags["cuisine_preference"] = "local"

    return GroundedPreferences(
        query_id=constraints.query_id,
        poi_weights=poi_weights,
        cuisine_weights=cuisine_weights,
        pace_weight=pace_weight,
        transport_weight=transport_weight,
        budget_weight=budget_weight,
        tags=tags,
    )
