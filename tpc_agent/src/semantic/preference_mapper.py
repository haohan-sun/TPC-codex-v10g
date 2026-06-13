"""通用偏好映射。"""

from __future__ import annotations

from typing import Any

from src.data_layer.schema import ConstraintCard, Constraints


def map_preferences(constraints: Constraints) -> dict[str, float]:
    """从约束卡片提取 POI/行为偏好权重。

    Args:
        constraints: 约束集合。

    Returns:
        dict[str, float]: 关键词/POI → 权重。
    """
    weights: dict[str, float] = {}

    for card in constraints.cards:
        if card.category == "attraction":
            name = card.parameters.get("must_visit_poi")
            if name:
                weights[str(name)] = 3.0
        if card.category == "spatial" and card.parameters.get("anchor_poi"):
            weights[str(card.parameters["anchor_poi"])] = 2.5

    return weights
