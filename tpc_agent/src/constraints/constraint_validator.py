"""约束覆盖率与一致性校验。"""

from __future__ import annotations

from src.data_layer.schema import ConstraintCard, Constraints


# 规划最少需要的全局字段
REQUIRED_GLOBAL_FIELDS = ("start_city", "target_city", "days", "people_number")

# 互斥偏好检测
PACE_CONFLICTS = {
    "relaxed": "intensive",
    "intensive": "relaxed",
}


def validate_constraints(constraints: Constraints) -> list[str]:
    """检查约束卡片覆盖率与冲突。

    检查项：
        1. 全局参数是否齐全（出发/目的城市、天数、人数）；
        2. 是否存在矛盾偏好（如同时要求轻松和紧凑）；
        3. 预算约束是否出现非正数；
        4. hard_logic_py 是否存在未解析卡片（category=logic）。

    Args:
        constraints: 约束集合。

    Returns:
        list[str]: 问题描述列表；空列表表示通过基本校验。
    """
    issues: list[str] = []
    gp = constraints.global_params

    # 1) 全局字段完整性
    for field in REQUIRED_GLOBAL_FIELDS:
        value = gp.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            issues.append(f"缺少必要全局参数: {field}")

    days = gp.get("days")
    people = gp.get("people_number")
    if isinstance(days, int) and days <= 0:
        issues.append(f"days 必须为正整数，当前值: {days}")
    if isinstance(people, int) and people <= 0:
        issues.append(f"people_number 必须为正整数，当前值: {people}")

    # 2) 卡片级检查
    pace_values = _collect_pace_preferences(constraints.cards)
    for pace in pace_values:
        conflict = PACE_CONFLICTS.get(pace)
        if conflict and conflict in pace_values:
            issues.append(f"偏好冲突: 同时存在 {pace} 与 {conflict} 节奏要求")

    # 3) 预算合法性
    for card in constraints.cards:
        if card.category != "budget":
            continue
        max_cost = card.parameters.get("max_cost")
        if max_cost is not None:
            try:
                if float(max_cost) <= 0:
                    issues.append(f"预算约束非正数: {card.card_id} -> {max_cost}")
            except (TypeError, ValueError):
                issues.append(f"预算约束无法解析为数字: {card.card_id}")

    # 4) 未解析 DSL 提醒（不阻断，但提示覆盖率风险）
    unparsed = [c for c in constraints.cards if c.category == "logic"]
    if unparsed:
        issues.append(
            f"存在 {len(unparsed)} 条未分类 hard_logic 约束，建议补充规则或 LLM 解析"
        )

    # 5) 人数卡片与 global_params 一致性
    people_cards = [
        c for c in constraints.cards if c.category == "people"
    ]
    for card in people_cards:
        card_people = card.parameters.get("people_number")
        if card_people is not None and people is not None and card_people != people:
            issues.append(
                f"人数不一致: global_params={people}, card {card.card_id}={card_people}"
            )

    return issues


def _collect_pace_preferences(cards: list[ConstraintCard]) -> set[str]:
    """收集所有节奏偏好值。"""
    pace_values: set[str] = set()
    for card in cards:
        if card.category != "preference":
            continue
        pace = card.parameters.get("pace")
        if isinstance(pace, str):
            pace_values.add(pace)
    return pace_values
