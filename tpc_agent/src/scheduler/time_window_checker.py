"""时间窗与 activity 顺序检查。"""

from __future__ import annotations

from src.data_layer.schema import Plan
from src.planner.plan_utils import time_to_minutes


def _check_time_order(activities: list[dict]) -> list[str]:
    issues: list[str] = []
    prev_end = -1
    for act in activities:
        st = time_to_minutes(act.get("start_time", "00:00"))
        et = time_to_minutes(act.get("end_time", "00:00"))
        if st < prev_end:
            issues.append(f"{act.get('type')} 开始时间早于上一活动结束")
        if et < st:
            issues.append(f"{act.get('type')} 结束早于开始")
        prev_end = max(prev_end, et)
        for seg in act.get("transports") or []:
            tst = time_to_minutes(seg.get("start_time", "00:00"))
            tet = time_to_minutes(seg.get("end_time", "00:00"))
            if tet < tst:
                issues.append(f"transport {seg.get('mode')} 时间无效")
    return issues


def check_time_windows(plan: Plan) -> list[str]:
    """检查各日 activity 时间顺序。"""
    official = plan.metadata.get("official_plan") or {}
    issues: list[str] = []
    for day in official.get("itinerary", []):
        day_issues = _check_time_order(day.get("activities", []))
        issues.extend(f"Day{day.get('day')}: {msg}" for msg in day_issues)
    return issues


def apply_time_window_check(plan: Plan) -> Plan:
    """写入 time_issues 到 metadata。"""
    plan.metadata["time_issues"] = check_time_windows(plan)
    return plan
