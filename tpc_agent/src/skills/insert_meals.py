"""技能：插入餐饮。"""

from src.data_layer.schema import CandidatePool, Plan


def insert_meals(plan: Plan, candidates: CandidatePool) -> Plan:
    """在饭点时段插入合适餐厅。

    Args:
        plan: 当前计划。
        candidates: 候选池（含餐厅）。

    Returns:
        Plan: 含餐饮的计划。
    """
    raise NotImplementedError
