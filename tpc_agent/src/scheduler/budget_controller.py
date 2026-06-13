"""预算控制：餐饮/总成本粗估与裁剪。"""

from __future__ import annotations

from src.data_layer.schema import Constraints, Plan
from src.planner.constraint_profile import extract_planning_constraints


def _plan_dining_cost(plan: Plan) -> float:
    official = plan.metadata.get("official_plan") or {}
    total = 0.0
    for day in official.get("itinerary", []):
        for act in day.get("activities", []):
            if act.get("type") in ("breakfast", "lunch", "dinner"):
                total += float(act.get("cost", 0))
    return total


def control_budget(plan: Plan, constraints: Constraints) -> Plan:
    """超餐饮预算时在 metadata 标记（供 repair 使用）。"""
    pc = extract_planning_constraints(constraints)
    if pc.dining_budget is None:
        return plan

    dining_cost = _plan_dining_cost(plan)
    plan.metadata["budget_report"] = {
        "dining_cost": dining_cost,
        "dining_budget": pc.dining_budget,
        "over_dining": dining_cost > pc.dining_budget + 0.1,
    }
    return plan
