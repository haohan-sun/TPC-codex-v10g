"""技能：最后一天保守安排。"""

from src.data_layer.schema import Plan


def final_day_conservative(plan: Plan) -> Plan:
    """最后一天减少景点、预留返程时间。

    Args:
        plan: 当前计划。

    Returns:
        Plan: 调整后的计划。
    """
    raise NotImplementedError
