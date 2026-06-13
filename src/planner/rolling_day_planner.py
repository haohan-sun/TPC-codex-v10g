"""滚动时域逐日规划。"""

from __future__ import annotations

from src.data_layer.schema import Activity, CandidatePool, Constraints, DayPlan, Plan
from src.planner.plan_builder import build_full_plan_dict, ensure_required_accommodations
from src.planner.state_tracker import init_state, update_state


def rolling_horizon_plan(
    constraints: Constraints,
    candidates: CandidatePool,
    initial_plan: Plan,
    preferences=None,
) -> Plan:
    """滚动生成完整 plan，写入 day_plans 与 metadata.official_plan。

    Args:
        constraints: 约束集合。
        candidates: 候选池。
        initial_plan: 多日分配结果。
        preferences: 语义偏好（可选，从 metadata 读取）。

    Returns:
        Plan: 含完整日程与 official_plan 字典。
    """
    prefs = preferences or initial_plan.metadata.get("preferences")
    official = build_full_plan_dict(constraints, candidates, prefs, policy=initial_plan.policy)
    official = ensure_required_accommodations(official, candidates)

    state = init_state(initial_plan, budget=float(constraints.global_params.get("budget") or 999999))
    day_plans: list[DayPlan] = []

    for day_entry in official.get("itinerary", []):
        day_num = day_entry.get("day", len(day_plans) + 1)
        acts = []
        for i, act in enumerate(day_entry.get("activities", [])):
            acts.append(Activity(
                activity_id=f"d{day_num}_a{i}",
                poi_id=act.get("position", act.get("type", "")),
                name=act.get("position", act.get("type", "")),
                activity_type=act.get("type", ""),
                start_time=act.get("start_time", ""),
                end_time=act.get("end_time", ""),
                metadata=act,
            ))
        dp = DayPlan(day_index=day_num - 1, date=f"Day{day_num}", activities=acts)
        day_plans.append(dp)
        state = update_state(state, dp)

    initial_plan.day_plans = day_plans
    initial_plan.metadata["official_plan"] = official
    initial_plan.metadata["plan_state"] = state
    initial_plan.metadata["constraints"] = constraints
    initial_plan.metadata["candidates"] = candidates
    initial_plan.metadata["preferences"] = prefs
    return initial_plan
