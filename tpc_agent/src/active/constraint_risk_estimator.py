"""约束风险评估。

结合不确定性分析与约束严重程度，输出风险画像，供 active_query_selector 决定查什么数据。
"""

from __future__ import annotations

from src.active.uncertainty_analyzer import analyze_uncertainty
from src.data_layer.schema import ConstraintCard, Constraints, Query, RiskProfile

# 各类约束若出错对 verifier 的影响权重（越高越致命）
CATEGORY_SEVERITY: dict[str, float] = {
    "logic": 0.95,
    "budget": 0.90,
    "spatial": 0.85,
    "transport": 0.85,
    "accommodation": 0.80,
    "ticket": 0.80,
    "temporal": 0.75,
    "people": 0.75,
    "attraction": 0.70,
    "dietary": 0.50,
    "preference": 0.40,
}

# 高风险阈值：超过此值视为需要优先查数据
HIGH_RISK_THRESHOLD = 0.55


def estimate_constraint_risk(query: Query, constraints: Constraints) -> RiskProfile:
    """判断 query 最可能在哪些约束维度出错。

    风险分数 = 不确定性 × 严重程度，并叠加硬约束优先级加成。

    Args:
        query: 用户查询。
        constraints: 约束集合。

    Returns:
        RiskProfile: 含各维度 risk_scores 与 high_risk_categories 列表。
    """
    uncertainty = analyze_uncertainty(constraints)
    risk_scores: dict[str, float] = {}

    # 统计各类别硬约束数量，用于加成
    hard_counts = _count_hard_cards(constraints.cards)

    for category, uncert in uncertainty.items():
        severity = CATEGORY_SEVERITY.get(category, 0.5)
        hard_boost = min(0.15, 0.05 * hard_counts.get(category, 0))
        risk = min(1.0, uncert * 0.55 + severity * 0.35 + hard_boost)
        risk_scores[category] = round(risk, 4)

    # 额外提升：存在 validation_issues 时，budget/spatial 风险上调
    issues = constraints.global_params.get("validation_issues") or []
    if issues:
        for cat in ("budget", "spatial", "logic"):
            if cat in risk_scores:
                risk_scores[cat] = min(1.0, risk_scores[cat] + 0.1)

    # 按分数降序取高风险类别
    high_risk = [
        cat for cat, score in sorted(risk_scores.items(), key=lambda x: -x[1])
        if score >= HIGH_RISK_THRESHOLD
    ]

    return RiskProfile(
        query_id=query.query_id,
        risk_scores=risk_scores,
        high_risk_categories=high_risk,
    )


def _count_hard_cards(cards: list[ConstraintCard]) -> dict[str, int]:
    """统计各类别硬约束卡片数量。"""
    counts: dict[str, int] = {}
    for card in cards:
        if card.is_hard:
            counts[card.category] = counts.get(card.category, 0) + 1
    return counts
