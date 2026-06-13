"""行程节奏语义映射。"""

from __future__ import annotations

from src.data_layer.schema import ConstraintCard, Constraints


def map_pace(constraints: Constraints, text: str = "") -> float:
    """将节奏描述映射为 0~1 权重（0=悠闲，1=紧凑）。

    Args:
        constraints: 约束集合。
        text: 自然语言描述。

    Returns:
        float: 节奏权重。
    """
    lowered = text.lower()
    if any(k in lowered for k in ("not too tired", "不要太累", "轻松", "relaxed")):
        return 0.3
    if any(k in lowered for k in ("packed", "紧凑", "as many", "尽量多")):
        return 0.8

    for card in constraints.cards:
        if card.category == "preference":
            pace = card.parameters.get("pace")
            if pace == "relaxed":
                return 0.3
            if pace == "intensive":
                return 0.8

    return 0.5
