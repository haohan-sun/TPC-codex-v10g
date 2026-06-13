"""餐饮偏好语义映射。"""

from __future__ import annotations

from src.data_layer.schema import ConstraintCard, Constraints


def map_cuisine_preferences(constraints: Constraints, text: str = "") -> dict[str, float]:
    """将餐饮相关描述映射为菜系权重。

    Args:
        constraints: 约束集合。
        text: 自然语言描述。

    Returns:
        dict[str, float]: 菜系 → 权重。
    """
    weights: dict[str, float] = {}
    lowered = text.lower()

    if any(k in lowered for k in ("local food", "local cuisine", "本地", "特色")):
        weights["local"] = 2.0
        weights["Sichuan"] = 1.0

    for card in constraints.cards:
        if card.category == "dietary":
            pref = card.parameters.get("cuisine_preference")
            if pref:
                weights[str(pref)] = 1.5

    return weights
