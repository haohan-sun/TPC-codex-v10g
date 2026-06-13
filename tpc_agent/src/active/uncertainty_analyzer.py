"""不确定性分析（Active SLAM 迁移）。

核心思想：在查数据之前，先判断哪些约束维度信息不足、最容易导致规划失败。
"""

from __future__ import annotations

from src.data_layer.schema import ConstraintCard, Constraints

# 各约束类别的基础不确定性权重（越高表示越难从 query 直接得到足够信息）
CATEGORY_UNCERTAINTY_BASE: dict[str, float] = {
    "logic": 0.95,        # 未解析的 hard_logic DSL
    "spatial": 0.80,      # 距离/位置类约束需要查 POI 坐标
    "budget": 0.75,       # 预算需要查价格数据
    "accommodation": 0.70,  # 酒店类型/位置需要查酒店库
    "transport": 0.65,      # 交通方式/城际选项需要查交通数据
    "attraction": 0.60,     # 必去景点需要确认 POI 是否存在
    "dietary": 0.55,        # 餐饮偏好需要查餐厅标签
    "preference": 0.45,     # 软偏好，信息相对模糊
    "ticket": 0.40,         # 票务通常可由人数推导
    "temporal": 0.25,       # 天数通常已在 metadata 中
    "people": 0.20,         # 人数通常已在 metadata 中
}


def analyze_uncertainty(constraints: Constraints) -> dict[str, float]:
    """分析各约束维度的不确定性分数（0~1，越高越不确定）。

    评估依据：
        1. 该类别约束卡片数量；
        2. 参数是否完整（如 budget 缺 max_cost）；
        3. 是否存在未解析 DSL（category=logic）；
        4. global_params 中的 validation_issues。

    Args:
        constraints: 约束集合。

    Returns:
        dict[str, float]: 维度(category) → 不确定性分数。
    """
    scores: dict[str, float] = {}
    cards_by_category: dict[str, list[ConstraintCard]] = {}

    for card in constraints.cards:
        cards_by_category.setdefault(card.category, []).append(card)

    # 遍历已有卡片类别，累加不确定性
    for category, cards in cards_by_category.items():
        base = CATEGORY_UNCERTAINTY_BASE.get(category, 0.5)
        incompleteness = _category_incompleteness(cards)
        # 多条同类别约束会略微提高不确定性（约束组合更复杂）
        count_factor = min(1.0, 0.1 * (len(cards) - 1))
        scores[category] = min(1.0, base * 0.6 + incompleteness * 0.3 + count_factor * 0.1)

    # 对可能出现但未显式出现的维度给出默认不确定性
    gp = constraints.global_params
    if gp.get("target_city") and "spatial" not in scores:
        scores["spatial"] = 0.35  # 仅有城市名，POI 详情仍未知

    if not any(c.category == "budget" for c in constraints.cards):
        # 无预算约束时，预算维度不确定性较低
        scores.setdefault("budget", 0.15)

    # validation_issues 会整体抬高相关维度
    issues = gp.get("validation_issues") or []
    if issues:
        boost = min(0.2, 0.05 * len(issues))
        for key in list(scores.keys()):
            scores[key] = min(1.0, scores[key] + boost)

    return scores


def _category_incompleteness(cards: list[ConstraintCard]) -> float:
    """计算一组卡片的信息不完整度（0~1）。"""
    if not cards:
        return 0.0

    incomplete_flags: list[float] = []
    for card in cards:
        params = card.parameters

        if card.category == "logic":
            # 未分类 DSL，信息最不完整
            incomplete_flags.append(1.0 if not params.get("parsed", True) else 0.8)
        elif card.category == "budget":
            incomplete_flags.append(0.0 if params.get("max_cost") is not None else 0.9)
        elif card.category == "spatial":
            if params.get("role") in ("start", "target"):
                incomplete_flags.append(0.1)  # 城市级信息已够
            elif params.get("anchor_poi"):
                incomplete_flags.append(0.3)  # 有锚点名称，但缺坐标
            else:
                incomplete_flags.append(0.6)
        elif card.category == "accommodation":
            incomplete_flags.append(0.2 if params.get("required_type") else 0.5)
        elif card.category == "attraction":
            incomplete_flags.append(0.4 if params.get("must_visit_poi") else 0.6)
        else:
            incomplete_flags.append(0.2)

    return sum(incomplete_flags) / len(incomplete_flags)
