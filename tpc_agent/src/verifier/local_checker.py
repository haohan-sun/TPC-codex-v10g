"""本地轻量规则检查（票务/预算/时间）。"""

from __future__ import annotations

from src.constraints.constraint_parser import parse_constraints
from src.data_layer.schema import Constraints, Plan
from src.planner.constraint_profile import extract_planning_constraints


def run_local_checker(plan: Plan, constraints: Constraints) -> Plan:
    """检查 tickets/cars 与约束一致性。"""
    pc = extract_planning_constraints(constraints)
    official = plan.metadata.get("official_plan") or {}
    issues: list[str] = []

    for day in official.get("itinerary", []):
        for act in day.get("activities", []):
            atype = act.get("type", "")
            if atype in ("attraction", "airplane", "train"):
                tickets = act.get("tickets")
                if tickets is not None and tickets != pc.activity_tickets:
                    issues.append(f"{atype} tickets={tickets}, 期望 {pc.activity_tickets}")
            for seg in act.get("transports") or []:
                mode = seg.get("mode", "")
                if mode == "metro" and "tickets" in seg:
                    if seg["tickets"] != pc.metro_tickets:
                        issues.append(f"metro tickets={seg['tickets']}, 期望 {pc.metro_tickets}")
                if mode == "taxi" and "cars" in seg:
                    if seg["cars"] != pc.taxi_cars:
                        issues.append(f"taxi cars={seg['cars']}, 期望 {pc.taxi_cars}")

    budget = plan.metadata.get("budget_report") or {}
    if budget.get("over_dining"):
        issues.append(
            f"餐饮超预算: {budget.get('dining_cost')} > {budget.get('dining_budget')}"
        )

    issues.extend(plan.metadata.get("time_issues") or [])
    plan.metadata["local_check_issues"] = issues
    return plan
