"""技能：锁定必去景点。"""

from src.data_layer.schema import Plan


def lock_must_visit(plan: Plan, must_visit_ids: list[str]) -> Plan:
    """强制插入必去 POI 并保护不被后续步骤移除。

    Args:
        plan: 当前计划。
        must_visit_ids: 必去 POI ID 列表。

    Returns:
        Plan: 更新后计划。
    """
    raise NotImplementedError
