"""滚动规划状态追踪。"""

from __future__ import annotations

from src.data_layer.schema import DayPlan, Plan, PlanState


def init_state(plan: Plan, budget: float = 999999.0) -> PlanState:
    """初始化规划状态。"""
    return PlanState(
        current_day=0,
        remaining_budget=budget,
        remaining_must_visit=list(plan.metadata.get("must_visit", [])),
    )


def update_state(state: PlanState, day_plan: DayPlan) -> PlanState:
    """完成一天后更新状态。"""
    visited = list(state.visited_poi_ids)
    for act in day_plan.activities:
        if act.poi_id:
            visited.append(act.poi_id)
    cost = sum(float(act.metadata.get("cost", 0)) for act in day_plan.activities if act.metadata)
    return PlanState(
        current_day=day_plan.day_index + 1,
        remaining_budget=max(0, state.remaining_budget - cost),
        current_location={"last_poi": day_plan.activities[-1].name if day_plan.activities else ""},
        remaining_must_visit=state.remaining_must_visit,
        visited_poi_ids=visited,
    )
