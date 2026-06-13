"""技能：选择酒店锚点。"""

from src.data_layer.schema import CandidatePool, Plan


def choose_hotel_anchor(plan: Plan, candidates: CandidatePool) -> Plan:
    """为每天选择酒店锚点，减少往返。

    Args:
        plan: 当前计划。
        candidates: 候选池。

    Returns:
        Plan: 含酒店锚点的计划。
    """
    raise NotImplementedError
