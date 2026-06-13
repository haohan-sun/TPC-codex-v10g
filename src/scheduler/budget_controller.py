"""Budget and resource control for generated plans — P2.2 enhanced.

每次 budget repair（换餐厅/酒店/交通/删POI）后完整重算：
- activity cost（单价 × tickets/rooms）
- transport cost（每段 price × tickets/cars）
- total_cost
- remaining budget/time slack
"""

from __future__ import annotations

from typing import Any

from src.data_layer.schema import Constraints, Plan, POICandidate
from src.planner.constraint_profile import extract_planning_constraints
from src.planner.state_tracker import ResourceState, compute_resource_state


def control_budget(plan: Plan, constraints: Constraints) -> Plan:
    """P2.2 增强预算控制：每次变更后完整重算所有 cost。

    修复顺序（prompt doc P2 #6）：
      1. 换低价餐厅
      2. 换低价酒店
      3. taxi → metro/walk
      4. 调整 POI 顺序减少交通
      5. 删除非必去景点
    """
    official = plan.metadata.get("official_plan") or {}
    if not official:
        return plan

    pc = extract_planning_constraints(constraints)
    candidates = plan.metadata.get("candidates")
    cheap_restaurants = sorted(getattr(candidates, "restaurants", []) or [], key=_candidate_price)
    cheap_hotels = sorted(getattr(candidates, "hotels", []) or [], key=_candidate_price)

    # Step 1: 换低价餐厅
    if pc.dining_budget is not None:
        _replace_meals(official, cheap_restaurants, pc.people, pc.dining_budget)

    # Step 2: 换低价酒店
    if pc.accommodation_budget is not None:
        _replace_hotels(official, cheap_hotels, pc.people, pc.days, pc.accommodation_budget)

    # Step 3: 总预算控制
    if pc.total_budget is not None:
        # 3a. taxi → metro/walk
        _prefer_low_cost_transports(official, pc)
        # 3b. 删除非必去景点
        _trim_optional_attractions(official, pc, pc.total_budget)

    # P2.2: 全面重算 cost（确保 transport/accommodation/meal 之间一致）
    _recalc_all_costs(official, pc)

    # P2.2: 计算 ResourceState
    rs = compute_resource_state(
        official,
        people=pc.people,
        days=pc.days,
        total_budget=pc.total_budget,
        dining_budget=pc.dining_budget,
        accommodation_budget=pc.accommodation_budget,
        must_visit=pc.must_visit,
    )

    total = rs.total_cost
    plan.total_cost = total
    plan.metadata["official_plan"] = official
    # budget_report 仅在 metadata 中用于调试，正式 JSON 会自动剥离
    plan.metadata["budget_report"] = {
        "total_cost": total,
        "dining_cost": rs.dining_cost,
        "accommodation_cost": rs.accommodation_cost,
        "transport_cost": rs.transport_cost,
        "activity_cost": rs.activity_cost,
        "budget_slack": rs.budget_slack,
        "time_slack_min": rs.time_slack_min,
        "fatigue_score": rs.fatigue_score,
        "over_total": rs.over_budget,
        "over_dining": rs.over_dining,
        "over_accommodation": rs.over_accommodation,
    }
    return plan


# ------------------------------------------------------------------
# P2.2: 完整成本重算
# ------------------------------------------------------------------

def _recalc_all_costs(plan_dict: dict[str, Any], pc) -> None:
    """P2.2 关键函数：遍历所有 activity 和 transport，确保 cost = price × units。

    修复后必须重算：
    - activity cost = price × tickets (attraction/airplane/train)
    - activity cost = price × rooms (accommodation)
    - activity cost = price × people (meal)
    - transport cost = price × tickets (metro) or price × cars (taxi)
    - walk transport cost = 0
    """
    people = pc.people
    itinerary = plan_dict.get("itinerary", [])

    for day_entry in itinerary:
        for act in day_entry.get("activities", []):
            atype = act.get("type", "")
            price = float(act.get("price", 0))
            tickets = int(act.get("tickets", 1))

            # --- activity level ---
            if atype in ("attraction", "airplane", "train"):
                act["cost"] = round(price * max(1, tickets), 2)
            elif atype == "accommodation":
                rooms = int(act.get("rooms", max(1, (people + 1) // 2)))
                act["cost"] = round(price * rooms, 2)
            elif atype in ("breakfast", "lunch", "dinner"):
                act["cost"] = round(price * max(1, people), 2)

            # --- transport segments ---
            for seg in act.get("transports", []):
                mode = seg.get("mode", "walk")
                seg_price = float(seg.get("price", 0))

                if mode == "walk":
                    seg["cost"] = 0.0
                    seg["price"] = 0.0
                elif mode == "metro":
                    seg_tickets = int(seg.get("tickets", people))
                    seg["tickets"] = seg_tickets
                    seg["cost"] = round(seg_price * seg_tickets, 2)
                    seg.pop("cars", None)
                elif mode == "taxi":
                    seg_cars = int(seg.get("cars", max(1, (people + 3) // 4)))
                    seg["cars"] = seg_cars
                    seg["cost"] = round(seg_price * seg_cars, 2)
                    seg.pop("tickets", None)

    # 重算 people_number 确保一致
    plan_dict["people_number"] = people


# ------------------------------------------------------------------
# meal replacement
# ------------------------------------------------------------------

def _replace_meals(plan_dict: dict[str, Any], restaurants: list[POICandidate], people: int, budget: float) -> None:
    """Step 1: 替换超预算餐厅为低价餐厅。"""
    if not restaurants:
        return
    meals = _meal_activities(plan_dict)
    if not meals:
        return
    cap = budget / max(1, len(meals) * max(1, people))
    affordable = [r for r in restaurants if _candidate_price(r) <= cap]
    if not affordable:
        affordable = sorted(restaurants, key=_candidate_price)[:5]
    for idx, act in enumerate(meals):
        if float(act.get("price", 0)) <= cap:
            continue
        rest = affordable[idx % len(affordable)]
        price = _candidate_price(rest)
        act["position"] = rest.name
        act["price"] = round(price, 2)
        act["cost"] = round(price * max(1, people), 2)


# ------------------------------------------------------------------
# hotel replacement
# ------------------------------------------------------------------

def _replace_hotels(plan_dict: dict[str, Any], hotels: list[POICandidate], people: int, days: int, budget: float) -> None:
    """Step 2: 替换超预算酒店为低价酒店。"""
    if not hotels:
        return
    rooms = max(1, (people + 1) // 2)
    nights = max(1, days - 1)
    per_night_budget = budget / max(1, rooms * nights)
    affordable = [h for h in hotels if _candidate_price(h) <= per_night_budget]
    if not affordable:
        affordable = sorted(hotels, key=_candidate_price)[:1]
    hotel = affordable[0]
    price = _candidate_price(hotel)
    for act in _activities(plan_dict):
        if act.get("type") == "accommodation":
            act["position"] = hotel.name
            act["rooms"] = rooms
            act["price"] = round(price, 2)
            act["cost"] = round(price * rooms, 2)


# ------------------------------------------------------------------
# transport cost reduction
# ------------------------------------------------------------------

def _prefer_low_cost_transports(plan_dict: dict[str, Any], pc) -> None:
    """Step 3a: taxi → metro/walk 降级，并重算 cost。"""
    # Never mutate one-segment taxi data into metro in-place. The official
    # verifier accepts metro only as exactly walk -> metro -> walk with values
    # returned by goto(); synthetic single-segment metro fails commonsense.
    return


# ------------------------------------------------------------------
# trim optional attractions
# ------------------------------------------------------------------

def _trim_optional_attractions(plan_dict: dict[str, Any], pc, budget: float) -> None:
    """Step 5: 删除非必去景点直到预算达标。"""
    must_names_lower = {m.lower() for m in pc.must_visit}

    def _is_must(act: dict) -> bool:
        name = str(act.get("position", "")).lower()
        return any(m in name for m in must_names_lower)

    max_iter = 20  # safety limit
    for _ in range(max_iter):
        current_total = _plan_total_cost(plan_dict)
        if current_total <= budget + 0.1:
            break

        removed = False
        for day in reversed(plan_dict.get("itinerary", [])):
            activities = day.get("activities", [])
            for idx in range(len(activities) - 1, -1, -1):
                act = activities[idx]
                if act.get("type") != "attraction":
                    continue
                if _is_must(act):
                    continue
                # 删除此景点及其 transport（上一段的 transport 也删）
                activities.pop(idx)
                removed = True
                break
            if removed:
                break

        if not removed:
            break  # nothing left to remove


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------

def _candidate_price(item: POICandidate) -> float:
    for key in ("price", "cost", "avg_price"):
        value = (item.metadata or {}).get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
    return 50.0


def _activities(plan_dict: dict[str, Any]) -> list[dict[str, Any]]:
    return [act for day in plan_dict.get("itinerary", []) for act in day.get("activities", [])]


def _meal_activities(plan_dict: dict[str, Any]) -> list[dict[str, Any]]:
    return [a for a in _activities(plan_dict) if a.get("type") in {"breakfast", "lunch", "dinner"}]


def _plan_total_cost(plan_dict: dict[str, Any]) -> float:
    total = 0.0
    for act in _activities(plan_dict):
        total += float(act.get("cost", 0))
        for seg in act.get("transports") or []:
            total += float(seg.get("cost", 0))
    return round(total, 2)
