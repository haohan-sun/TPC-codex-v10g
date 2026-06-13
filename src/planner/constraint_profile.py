"""从约束卡片提取 planner 可用的结构化约束。"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.data_layer.schema import Constraints


@dataclass
class PlanningConstraints:
    """规划阶段结构化约束。"""

    people: int = 1
    days: int = 1
    start_city: str = ""
    target_city: str = ""
    dining_budget: float | None = None
    total_budget: float | None = None
    accommodation_budget: float | None = None
    hotel_near_anchor: str | None = None
    hotel_max_distance_km: float | None = None
    intercity_mode: str = "airplane"
    activity_tickets: int | None = None
    metro_tickets: int | None = None
    taxi_cars: int | None = None
    innercity_modes: set[str] = field(default_factory=set)
    must_visit: list[str] = field(default_factory=list)
    must_visit_types: list[str] = field(default_factory=list)
    forbidden_attraction_types: list[str] = field(default_factory=list)
    forbidden_pois: list[str] = field(default_factory=list)
    cuisine_preferences: list[str] = field(default_factory=list)
    required_hotel_type: str | None = None
    required_hotel_names: list[str] = field(default_factory=list)
    required_restaurant_names: list[str] = field(default_factory=list)
    prefer_metro: bool = True
    prefer_taxi_for_hotel: bool = True
    pace: str = "balanced"
    max_pois_per_day: int | None = None
    buffer_minutes: int = 20
    free_attraction: bool = False
    free_intercity: bool = False


def extract_planning_constraints(constraints: Constraints) -> PlanningConstraints:
    """从 Constraints 卡片/global_params 汇总规划约束。"""
    gp = constraints.global_params
    people = int(gp.get("people_number") or 1)
    days = int(gp.get("days") or 1)
    pc = PlanningConstraints(
        people=people,
        days=days,
        start_city=str(gp.get("start_city", "")),
        target_city=str(gp.get("target_city", "")),
        activity_tickets=people,
        metro_tickets=people,
        taxi_cars=max(1, (people + 3) // 4),
    )

    for card in constraints.cards:
        params = card.parameters or {}

        if card.category == "budget":
            btype = params.get("budget_type", "total")
            if btype == "free_attraction":
                pc.free_attraction = True
            elif btype == "free_intercity":
                pc.free_intercity = True
            max_cost = params.get("max_cost")
            if max_cost is not None:
                try:
                    val = float(max_cost)
                    if btype == "dining":
                        pc.dining_budget = val
                    elif btype == "accommodation":
                        pc.accommodation_budget = val
                    else:
                        pc.total_budget = val
                except (TypeError, ValueError):
                    pass

        elif card.category == "spatial" and params.get("target") == "accommodation":
            pc.hotel_near_anchor = params.get("anchor_poi")
            dist = params.get("max_distance_km")
            if dist is not None:
                try:
                    pc.hotel_max_distance_km = float(dist)
                except (TypeError, ValueError):
                    pass

        elif card.category == "transport":
            if params.get("intercity_mode"):
                pc.intercity_mode = str(params["intercity_mode"])
            if params.get("innercity_mode"):
                pc.innercity_modes.add(str(params["innercity_mode"]))
            if params.get("taxi_cars") is not None:
                try:
                    pc.taxi_cars = int(params["taxi_cars"])
                except (TypeError, ValueError):
                    pass

        elif card.category == "ticket":
            scope = params.get("scope", "activity")
            count = params.get("ticket_count")
            if count is not None:
                try:
                    n = int(count)
                    if scope == "metro":
                        pc.metro_tickets = n
                    elif scope == "activity":
                        pc.activity_tickets = n
                except (TypeError, ValueError):
                    pass

        elif card.category == "attraction" and params.get("must_visit_poi"):
            name = str(params["must_visit_poi"])
            if name not in pc.must_visit:
                pc.must_visit.append(name)

        elif card.category == "attraction" and params.get("must_visit_type"):
            atype = str(params["must_visit_type"])
            if atype not in pc.must_visit_types:
                pc.must_visit_types.append(atype)

        elif card.category == "attraction" and params.get("forbidden_attraction_type"):
            atype = str(params["forbidden_attraction_type"])
            if atype not in pc.forbidden_attraction_types:
                pc.forbidden_attraction_types.append(atype)

        elif card.category == "attraction" and params.get("forbidden_poi"):
            name = str(params["forbidden_poi"])
            if name not in pc.forbidden_pois:
                pc.forbidden_pois.append(name)

        elif card.category == "accommodation" and params.get("required_type"):
            pc.required_hotel_type = str(params["required_type"])

        elif card.category == "accommodation" and params.get("required_name"):
            name = str(params["required_name"])
            if name not in pc.required_hotel_names:
                pc.required_hotel_names.append(name)

        elif card.category == "dietary" and params.get("cuisine_preference"):
            cuisine = str(params["cuisine_preference"])
            if cuisine not in pc.cuisine_preferences:
                pc.cuisine_preferences.append(cuisine)

        elif card.category == "dietary" and params.get("restaurant_name"):
            name = str(params["restaurant_name"])
            if name not in pc.required_restaurant_names:
                pc.required_restaurant_names.append(name)

        elif card.category == "preference":
            if params.get("pace"):
                pc.pace = str(params["pace"])
            if params.get("max_pois_per_day") is not None:
                try:
                    pc.max_pois_per_day = int(params["max_pois_per_day"])
                except (TypeError, ValueError):
                    pass
            if params.get("buffer_minutes") is not None:
                try:
                    pc.buffer_minutes = int(params["buffer_minutes"])
                except (TypeError, ValueError):
                    pass

        elif card.category == "people" and params.get("people_number"):
            try:
                pc.people = int(params["people_number"])
                pc.activity_tickets = pc.people
                pc.metro_tickets = pc.people
                pc.taxi_cars = max(1, (pc.people + 3) // 4)
            except (TypeError, ValueError):
                pass

    if "metro" in pc.innercity_modes:
        pc.prefer_metro = True
    if "taxi" in pc.innercity_modes:
        pc.prefer_taxi_for_hotel = True

    return pc


def max_meal_price(pc: PlanningConstraints) -> float | None:
    """估算单人单餐上限价（用于选餐厅）。"""
    if pc.dining_budget is None:
        return None
    estimated_meals = max(1, pc.days * 3 - 1)
    return pc.dining_budget / (estimated_meals * max(pc.people, 1))
