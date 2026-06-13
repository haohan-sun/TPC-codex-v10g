"""语义落地与偏好权重。"""

from __future__ import annotations

from src.data_layer.schema import ActiveInfo, Constraints, GroundedPreferences
from src.semantic.cuisine_mapper import map_cuisine_preferences
from src.semantic.pace_mapper import map_pace
from src.semantic.preference_mapper import map_preferences
from src.skills.registry import call_skill
from src.skills.skill_types import SkillContext


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
    forbidden_attraction_types: list[str] = []
    required_attraction_types: list[str] = []
    forbidden_pois: list[str] = []

    # 预算约束 → 提高 budget_weight
    budget_weight = 0.5
    for card in constraints.cards:
        if card.category == "budget":
            budget_weight = 0.85
        if card.category == "attraction":
            params = card.parameters or {}
            if params.get("must_visit_type"):
                value = str(params["must_visit_type"])
                required_attraction_types.append(value)
                poi_weights[value] = max(poi_weights.get(value, 0), 2.0)
            if params.get("forbidden_attraction_type"):
                forbidden_attraction_types.append(str(params["forbidden_attraction_type"]))
            if params.get("forbidden_poi"):
                forbidden_pois.append(str(params["forbidden_poi"]))

    # 交通约束 → transport_weight
    transport_weight = 0.5
    for card in constraints.cards:
        if card.category == "transport":
            transport_weight = 0.75

    tags: dict = {}
    if "local" in cuisine_weights:
        tags["cuisine_preference"] = "local"
    if required_attraction_types:
        tags["required_attraction_types"] = required_attraction_types
    if forbidden_attraction_types:
        tags["forbidden_attraction_types"] = forbidden_attraction_types
    if forbidden_pois:
        tags["forbidden_pois"] = forbidden_pois

    # Local semantic skill: convert fuzzy natural-language intent into planner
    # hints without relying on any external API.
    skill_result = call_skill(
        "ground_travel_intent",
        {"constraints": constraints, "active_info": active_info, "nl_text": nl_text},
        SkillContext(constraints=constraints, metadata={"stage": "semantic"}),
    )
    skill_decision = skill_result.decision
    for key, value in (skill_decision.get("poi_weights") or {}).items():
        poi_weights[key] = max(poi_weights.get(key, 0.0), float(value))
    skill_tags = skill_decision.get("tags") or {}
    tags.update(skill_tags)
    tags["planning_hints"] = skill_decision.get("planning_hints") or {}
    tags["skills_used"] = sorted(set(tags.get("skills_used", []) + ["ground_travel_intent"]))

    return GroundedPreferences(
        query_id=constraints.query_id,
        poi_weights=poi_weights,
        cuisine_weights=cuisine_weights,
        pace_weight=pace_weight,
        transport_weight=transport_weight,
        budget_weight=budget_weight,
        tags=tags,
    )
