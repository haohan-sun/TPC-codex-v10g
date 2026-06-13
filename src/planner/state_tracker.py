"""滚动规划状态追踪 — P2.2 ResourceState 统一资源管理。

追踪维度：
- budget: total / dining / accommodation（剩余预算）
- time: 每日剩余可用时间
- fatigue: 疲劳度（连续景点过多时升高）
- location: 当前位置
- must_visit: 剩余必访景点
- slack: 预算/时间冗余量
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.data_layer.schema import DayPlan, Plan, PlanState
from src.planner.plan_utils import time_to_minutes


@dataclass
class ResourceState:
    """P2.2 统一资源状态。

    每次 plan 变更（换酒店/换餐厅/换交通/删POI）后调用 recalc 方法重算。
    """

    # --- budget ---
    total_budget: float | None = None
    dining_budget: float | None = None
    accommodation_budget: float | None = None
    remaining_total: float = 0.0

    # --- time ---
    total_days: int = 1
    daily_available_minutes: int = 12 * 60  # 08:00-20:00 = 720 min
    remaining_time_min: float = 0.0          # 当天剩余分钟

    # --- fatigue ---
    fatigue_score: float = 0.0               # 0=休息充分, 1=极度疲劳
    consecutive_pois: int = 0

    # --- location ---
    current_position: str = ""
    current_day: int = 0

    # --- must_visit ---
    remaining_must_visit: list[str] = field(default_factory=list)

    # --- computed ---
    total_cost: float = 0.0                  # 总花费
    dining_cost: float = 0.0
    accommodation_cost: float = 0.0
    transport_cost: float = 0.0
    activity_cost: float = 0.0
    budget_slack: float = 0.0                # 正值 = 有盈余
    time_slack_min: float = 0.0              # 正值 = 有时间余量

    # --- flags ---
    over_budget: bool = False
    over_dining: bool = False
    over_accommodation: bool = False


def compute_resource_state(
    plan_dict: dict[str, Any],
    people: int = 1,
    days: int = 1,
    total_budget: float | None = None,
    dining_budget: float | None = None,
    accommodation_budget: float | None = None,
    must_visit: list[str] | None = None,
) -> ResourceState:
    """从官方 plan dict 计算完整资源状态。

    此函数在 plan 构建完成后、以及每次 repair 后调用，
    确保所有成本/时间/疲劳数据一致。
    """
    rs = ResourceState(
        total_budget=total_budget,
        dining_budget=dining_budget,
        accommodation_budget=accommodation_budget,
        total_days=days,
        remaining_must_visit=list(must_visit or []),
    )

    itinerary = plan_dict.get("itinerary", [])
    people_n = int(plan_dict.get("people_number", people))

    for day_entry in itinerary:
        activities = day_entry.get("activities", [])
        prev_end = ""
        for act in activities:
            atype = act.get("type", "")
            cost = float(act.get("cost", 0))

            # 累计各项成本
            rs.total_cost += cost
            if atype in ("breakfast", "lunch", "dinner"):
                rs.dining_cost += cost
            elif atype == "accommodation":
                rs.accommodation_cost += cost
            elif atype in ("attraction",):
                rs.activity_cost += cost

            # 交通成本
            for seg in act.get("transports", []):
                rs.transport_cost += float(seg.get("cost", 0))

            # 追踪时间
            start_t = act.get("start_time", "")
            end_t = act.get("end_time", "")
            if start_t and end_t:
                try:
                    dur = time_to_minutes(end_t) - time_to_minutes(start_t)
                    if dur > 0:
                        rs.remaining_time_min += dur  # accumulate used time
                except (ValueError, TypeError):
                    pass

            # 疲劳追踪（连续景点）
            if atype == "attraction":
                rs.consecutive_pois += 1
            elif atype in ("breakfast", "lunch", "dinner"):
                rs.consecutive_pois = max(0, rs.consecutive_pois - 1)  # meal = rest

            prev_end = end_t

        # 日间重置疲劳
        if rs.consecutive_pois > 3:
            rs.fatigue_score += (rs.consecutive_pois - 3) * 0.1
        rs.consecutive_pois = 0  # reset for next day

    # 计算 slack
    total_available = days * rs.daily_available_minutes
    rs.time_slack_min = total_available - rs.remaining_time_min
    rs.remaining_time_min = rs.time_slack_min  # repurpose as slack

    if rs.total_budget is not None:
        rs.remaining_total = rs.total_budget - rs.total_cost
        rs.budget_slack = rs.remaining_total
        rs.over_budget = rs.total_cost > rs.total_budget + 0.1

    if rs.dining_budget is not None:
        rs.over_dining = rs.dining_cost > rs.dining_budget + 0.1

    if rs.accommodation_budget is not None:
        rs.over_accommodation = rs.accommodation_cost > rs.accommodation_budget + 0.1

    # 疲劳归一化
    rs.fatigue_score = min(1.0, rs.fatigue_score)

    return rs


def recalc_after_change(
    plan_dict: dict[str, Any],
    rs: ResourceState,
    *,
    changed_activity_index: int | None = None,
    changed_day_index: int | None = None,
    people: int | None = None,
    days: int | None = None,
) -> ResourceState:
    """局部重算 ResourceState（比全量 compute 更快）。

    在 budget_controller 每次修改（换餐厅/酒店/交通/删POI）后调用。
    对于简单变更直接 recalc cost；对于删 POI 等结构变更则回退到全量计算。
    """
    if changed_activity_index is not None and changed_day_index is not None:
        # 局部重算（只更新受影响的成本项）
        itinerary = plan_dict.get("itinerary", [])
        if changed_day_index < len(itinerary):
            activities = itinerary[changed_day_index].get("activities", [])
            if changed_activity_index < len(activities):
                act = activities[changed_activity_index]
                atype = act.get("type", "")
                old_cost = getattr(rs, "_prev_cost", None) or 0.0
                new_cost = float(act.get("cost", 0))
                rs.total_cost += new_cost - old_cost
                if atype in ("breakfast", "lunch", "dinner"):
                    rs.dining_cost += new_cost - old_cost
                elif atype == "accommodation":
                    rs.accommodation_cost += new_cost - old_cost

    # 重算 slack
    if rs.total_budget is not None:
        rs.remaining_total = rs.total_budget - rs.total_cost
        rs.budget_slack = rs.remaining_total
        rs.over_budget = rs.total_cost > rs.total_budget + 0.1

    if rs.dining_budget is not None:
        rs.over_dining = rs.dining_cost > rs.dining_budget + 0.1

    if rs.accommodation_budget is not None:
        rs.over_accommodation = rs.accommodation_cost > rs.accommodation_budget + 0.1

    return rs


# ------------------------------------------------------------------
# backward-compatible wrappers
# ------------------------------------------------------------------

def init_state(plan: Plan, budget: float = 999999.0) -> PlanState:
    """初始化规划状态（向后兼容）。"""
    return PlanState(
        current_day=0,
        remaining_budget=budget,
        remaining_must_visit=list(plan.metadata.get("must_visit", [])),
    )


def update_state(state: PlanState, day_plan: DayPlan) -> PlanState:
    """完成一天后更新状态（向后兼容）。"""
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
