"""技能：平衡行程强度。"""

from src.data_layer.schema import Plan


def balance_intensity(plan: Plan, pace_weight: float = 0.5) -> Plan:
    """调整每日景点数量与强度，避免过度疲劳。

    Args:
        plan: 当前计划。
        pace_weight: 节奏权重。

    Returns:
        Plan: 强度平衡后的计划。
    """
    raise NotImplementedError
