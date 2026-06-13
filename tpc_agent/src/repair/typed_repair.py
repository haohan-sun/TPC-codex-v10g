"""Typed verifier-feedback repair."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from src.data_layer.schema import CandidatePool, Constraints, ErrorType, OfficialPlan, POICandidate, TypedError
from src.planner.constraint_profile import extract_planning_constraints
from src.planner.plan_utils import add_minutes, time_to_minutes


def typed_repair(
    plan: OfficialPlan,
    errors: list[TypedError],
    constraints: Constraints,
    candidates: CandidatePool,
) -> OfficialPlan:
    """Dispatch local repairs by error type."""
    payload = deepcopy(plan.itinerary)
    pc = extract_planning_constraints(constraints)

    if not errors:
        return plan

    _repair_format(payload, pc)
    for error in errors:
        et = error.error_type
        if et == ErrorType.FORMAT:
            _repair_format(payload, pc)
        elif et == ErrorType.TICKET:
            _repair_tickets(payload, pc)
        elif et == ErrorType.TRANSPORT:
            _repair_transport(payload, pc)
            _repair_tickets(payload, pc)
        elif et == ErrorType.BUDGET:
            _repair_budget(payload, candidates, pc)
        elif et == ErrorType.TIME:
            _repair_time(payload)
        elif et == ErrorType.MEAL:
            _repair_meals(payload, candidates, pc)
        elif et == ErrorType.MUST_VISIT:
            _repair_must_visit(payload, constraints, candidates, pc)
        elif et == ErrorType.OPENING_HOURS:
            _repair_opening_hours(payload)
        else:
            _repair_format(payload, pc)
            _repair_tickets(payload, pc)
            _repair_time(payload)

    return OfficialPlan(query_id=plan.query_id, itinerary=payload, version=plan.version)


def _repair_format(plan: dict[str, Any], pc) -> None:
    plan.setdefault("people_number", pc.people)
    plan.setdefault("start_city", pc.start_city)
    plan.setdefault("target_city", pc.target_city)
    plan.setdefault("itinerary", [])
    for day_idx, day in enumerate(plan["itinerary"], start=1):
        day.setdefault("day", day_idx)
        day.setdefault("activities", [])
        for act in day["activities"]:
            act.setdefault("type", "attraction")
            act.setdefault("start_time", "09:00")
            act.setdefault("end_time", add_minutes(act["start_time"], 60))
            act.setdefault("price", 0.0)
            act.setdefault("cost", 0.0)
            act.setdefault("transports", [])
            if act["type"] in {"attraction", "airplane", "train"}:
                act.setdefault("tickets", pc.people)
            if act["type"] == "accommodation":
                act.setdefault("rooms", max(1, (pc.people + 1) // 2))
                act.setdefault("room_type", 1)
            if act["type"] == "airplane":
                act.setdefault("start", pc.start_city)
                act.setdefault("end", pc.target_city)
                # 不伪造 FlightID；缺少真实 ID 则标为无效（后续上层会移除）
                if not act.get("FlightID"):
                    act["_invalid_intercity"] = True
            if act["type"] == "train":
                act.setdefault("start", pc.start_city)
                act.setdefault("end", pc.target_city)
                if not act.get("TrainID"):
                    act["_invalid_intercity"] = True


def _repair_tickets(plan: dict[str, Any], pc) -> None:
    for act in _activities(plan):
        if act.get("type") in {"attraction", "airplane", "train"}:
            act["tickets"] = pc.activity_tickets or pc.people
        for seg in act.get("transports") or []:
            if seg.get("mode") == "metro":
                seg["tickets"] = pc.metro_tickets or pc.people
            if seg.get("mode") == "taxi":
                seg["cars"] = pc.taxi_cars or max(1, (pc.people + 3) // 4)


def _repair_transport(plan: dict[str, Any], pc) -> None:
    for day in plan.get("itinerary", []):
        prev_pos = ""
        prev_time = "09:00"
        for act in day.get("activities", []):
            pos = act.get("position") or act.get("end") or ""
            if pos and not act.get("transports") and prev_pos and act.get("type") not in {"airplane", "train"}:
                act["transports"] = [{
                    "start": prev_pos,
                    "end": pos,
                    "mode": "metro" if pc.prefer_metro else "taxi",
                    "start_time": prev_time,
                    "end_time": add_minutes(prev_time, 20),
                    "price": 5.0 if pc.prefer_metro else 30.0,
                    "cost": 5.0 * pc.people if pc.prefer_metro else 30.0 * (pc.taxi_cars or 1),
                    "distance": 2.0,
                    **({"tickets": pc.people} if pc.prefer_metro else {"cars": pc.taxi_cars or 1}),
                }]
            if pos:
                prev_pos = pos
            prev_time = act.get("end_time", prev_time)


def _repair_budget(plan: dict[str, Any], candidates: CandidatePool, pc) -> None:
    cheap_restaurants = sorted(candidates.restaurants or [], key=_candidate_price)
    cheap_hotels = sorted(candidates.hotels or [], key=_candidate_price)
    if pc.dining_budget and cheap_restaurants:
        meals = [a for a in _activities(plan) if a.get("type") in {"breakfast", "lunch", "dinner"}]
        cap = pc.dining_budget / max(1, len(meals) * pc.people)
        for i, act in enumerate(meals):
            rest = next((r for r in cheap_restaurants if _candidate_price(r) <= cap), cheap_restaurants[0])
            act["position"] = rest.name
            act["price"] = _candidate_price(rest)
            act["cost"] = round(act["price"] * pc.people, 2)
    if pc.accommodation_budget and cheap_hotels:
        rooms = max(1, (pc.people + 1) // 2)
        nights = max(1, pc.days - 1)
        hotel = next((h for h in cheap_hotels if _candidate_price(h) * rooms * nights <= pc.accommodation_budget), cheap_hotels[0])
        for act in _activities(plan):
            if act.get("type") == "accommodation":
                act["position"] = hotel.name
                act["rooms"] = rooms
                act["price"] = _candidate_price(hotel)
                act["cost"] = round(act["price"] * rooms, 2)


def _repair_time(plan: dict[str, Any]) -> None:
    for day in plan.get("itinerary", []):
        current = "06:00"
        for act in day.get("activities", []):
            start = act.get("start_time", current)
            if time_to_minutes(start) < time_to_minutes(current):
                duration = _duration(act)
                act["start_time"] = current
                act["end_time"] = add_minutes(current, duration)
            current = add_minutes(act.get("end_time", current), 10)


def _repair_meals(plan: dict[str, Any], candidates: CandidatePool, pc) -> None:
    restaurant = (sorted(candidates.restaurants or [], key=_candidate_price) or [None])[0]
    for day in plan.get("itinerary", []):
        existing = {a.get("type") for a in day.get("activities", [])}
        inserts = []
        for meal, start in (("breakfast", "08:00"), ("lunch", "12:00"), ("dinner", "18:00")):
            if meal not in existing:
                name = restaurant.name if restaurant else f"{pc.target_city} {meal}"
                price = _candidate_price(restaurant) if restaurant else 35.0
                inserts.append({
                    "type": meal,
                    "start_time": start,
                    "end_time": add_minutes(start, 45 if meal == "breakfast" else 60),
                    "position": name,
                    "price": price,
                    "cost": round(price * pc.people, 2),
                    "transports": [],
                })
        day.setdefault("activities", []).extend(inserts)
        day["activities"].sort(key=lambda a: time_to_minutes(a.get("start_time", "23:59")))


def _repair_must_visit(plan: dict[str, Any], constraints: Constraints, candidates: CandidatePool, pc) -> None:
    present = {str(a.get("position", "")).lower() for a in _activities(plan) if a.get("type") == "attraction"}
    missing = []
    for card in constraints.cards:
        params = card.parameters or {}
        name = params.get("must_visit_poi")
        if name and not any(str(name).lower() in p for p in present):
            missing.append(str(name))
    if not missing:
        return
    day = (plan.get("itinerary") or [{"day": 1, "activities": []}])[0]
    plan.setdefault("itinerary", [day])
    for name in missing:
        cand = _find_candidate(candidates.pois, name)
        price = _candidate_price(cand) if cand else 0.0
        day.setdefault("activities", []).append({
            "type": "attraction",
            "start_time": "15:00",
            "end_time": "16:30",
            "position": cand.name if cand else name,
            "price": price,
            "cost": round(price * pc.people, 2),
            "tickets": pc.people,
            "transports": [],
        })


def _repair_opening_hours(plan: dict[str, Any]) -> None:
    for act in _activities(plan):
        if act.get("type") == "attraction" and time_to_minutes(act.get("start_time", "09:00")) < time_to_minutes("09:00"):
            duration = _duration(act)
            act["start_time"] = "09:00"
            act["end_time"] = add_minutes("09:00", duration)
        if act.get("type") == "dinner" and time_to_minutes(act.get("start_time", "18:00")) < time_to_minutes("17:30"):
            duration = _duration(act)
            act["start_time"] = "17:30"
            act["end_time"] = add_minutes("17:30", duration)


def _activities(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [act for day in plan.get("itinerary", []) for act in day.get("activities", [])]


def _duration(act: dict[str, Any]) -> int:
    try:
        return max(30, time_to_minutes(act.get("end_time", "10:00")) - time_to_minutes(act.get("start_time", "09:00")))
    except Exception:
        return 60


def _candidate_price(item: POICandidate | None) -> float:
    if item is None:
        return 50.0
    for key in ("price", "cost", "avg_price"):
        value = (item.metadata or {}).get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
    return 50.0


def _find_candidate(items: list[POICandidate], name: str) -> POICandidate | None:
    name_l = name.lower()
    for item in items or []:
        if name_l in item.name.lower() or name_l == item.poi_id.lower():
            return item
    return None
