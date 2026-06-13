"""多日任务分配。"""

from __future__ import annotations

from src.data_layer.schema import CandidatePool, Constraints, DayAssignment, Plan


def allocate_pois_to_days(
    constraints: Constraints,
    candidates: CandidatePool,
    policy: str = "safe",
) -> Plan:
    """将 POI 分配到各天，并预生成官方 plan 骨架。

    Args:
        constraints: 约束集合。
        candidates: 候选池。
        policy: 规划策略。

    Returns:
        Plan: 含 day_assignments 与 metadata 中 official_plan 草稿。
    """
    gp = constraints.global_params
    num_days = int(gp.get("days") or 1)
    pois = candidates.pois or []

    per_day = max(1, len(pois) // max(num_days, 1)) if pois else 0
    assignments: list[DayAssignment] = []
    idx = 0
    for d in range(num_days):
        ids = []
        for _ in range(per_day):
            if idx < len(pois):
                ids.append(pois[idx].poi_id)
                idx += 1
        assignments.append(DayAssignment(day_index=d, date=f"Day{d + 1}", poi_ids=ids))

    plan = Plan(
        query_id=constraints.query_id,
        policy=policy,
        day_assignments=assignments,
        metadata={"stage": "allocated"},
    )
    return plan
