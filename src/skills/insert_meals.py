"""Meal insertion and restaurant choice skills."""

from __future__ import annotations

from typing import Any

from src.data_layer.schema import CandidatePool, Plan, POICandidate
from src.planner.plan_utils import add_minutes, time_to_minutes
from src.skills.skill_types import SkillContext, SkillResult


MEAL_WINDOWS = {
    "breakfast": ("07:30", "10:00", 45),
    "lunch": ("11:30", "14:00", 60),
    "dinner": ("17:30", "21:00", 60),
}


def insert_meals_by_route(
    payload: dict[str, Any],
    context: SkillContext | None = None,
) -> SkillResult:
    """Return local meal insertion patches for one day route."""
    day_activities = list(payload.get("day_activities") or [])
    restaurants = _restaurants_from_payload(payload, context)
    people = int(payload.get("people") or 1)
    dining_budget = payload.get("dining_budget")
    used_names = set(payload.get("used_names") or [])
    current_time = str(payload.get("current_time") or "09:00")

    existing = {str(a.get("type", "")) for a in day_activities}
    choices = _choose_restaurants(restaurants, people, dining_budget, used_names)
    patches: list[dict[str, Any]] = []

    for meal, (start, latest, duration) in MEAL_WINDOWS.items():
        if meal in existing:
            continue
        if time_to_minutes(current_time) > time_to_minutes(latest):
            continue
        rest = choices.get(meal)
        if rest is None:
            continue
        price = _price(rest, 35.0 if meal == "breakfast" else 50.0)
        patches.append({
            "op": "insert_activity",
            "type": meal,
            "start_time": max(_safe_time(current_time), start, key=time_to_minutes),
            "end_time": add_minutes(max(_safe_time(current_time), start, key=time_to_minutes), duration),
            "position": rest.name if rest else "",
            "price": round(price, 2),
            "cost": round(price * people, 2),
            "transports": [],
        })

    return SkillResult(
        name="insert_meals_by_route",
        category="schedule",
        decision={
            "meal_choices": {
                meal: (rest.name if rest else "")
                for meal, rest in choices.items()
            },
            "skipped_existing": sorted(existing & set(MEAL_WINDOWS)),
        },
        patches=patches,
        score=float(len(patches)),
        evidence=[p["type"] for p in patches],
    )


def select_meal_candidates(
    restaurants: list[POICandidate],
    *,
    people: int = 1,
    dining_budget: float | None = None,
    used_names: set[str] | None = None,
) -> SkillResult:
    choices = _choose_restaurants(restaurants, people, dining_budget, used_names or set())
    return SkillResult(
        name="insert_meals_by_route",
        category="schedule",
        decision={
            "breakfast_id": choices["breakfast"].poi_id if choices.get("breakfast") else "",
            "lunch_id": choices["lunch"].poi_id if choices.get("lunch") else "",
            "dinner_id": choices["dinner"].poi_id if choices.get("dinner") else "",
            "meal_choices": {
                meal: (rest.name if rest else "")
                for meal, rest in choices.items()
            },
        },
        score=float(sum(1 for v in choices.values() if v is not None)),
    )


def insert_meals(plan: Plan, candidates: CandidatePool) -> Plan:
    """Compatibility wrapper: annotate a plan with meal insertion advice."""
    result = insert_meals_by_route(
        {"restaurants": candidates.restaurants, "day_activities": []},
        SkillContext(candidates=candidates, policy=plan.policy),
    )
    plan.metadata["skill_insert_meals"] = result.decision
    return plan


def _restaurants_from_payload(
    payload: dict[str, Any],
    context: SkillContext | None,
) -> list[POICandidate]:
    if payload.get("restaurants") is not None:
        return list(payload["restaurants"])
    if payload.get("candidates") is not None:
        return list(getattr(payload["candidates"], "restaurants", []) or [])
    if context and context.candidates is not None:
        return list(getattr(context.candidates, "restaurants", []) or [])
    return []


def _choose_restaurants(
    restaurants: list[POICandidate],
    people: int,
    dining_budget: float | None,
    used_names: set[str],
) -> dict[str, POICandidate | None]:
    if not restaurants:
        return {"breakfast": None, "lunch": None, "dinner": None}

    pool = sorted(restaurants, key=lambda r: (_price(r, 999.0), -float(r.score or 0.0), r.name))
    if dining_budget is not None:
        cap = float(dining_budget) / max(people * 3, 1)
        affordable = [r for r in pool if _price(r, 999.0) <= cap * 1.2]
        if affordable:
            pool = affordable

    fresh = [r for r in pool if r.name not in used_names] or pool
    choices: dict[str, POICandidate | None] = {}
    for idx, meal in enumerate(("breakfast", "lunch", "dinner")):
        choices[meal] = fresh[idx % len(fresh)]
    return choices


def _price(item: POICandidate | None, default: float) -> float:
    if item is None:
        return default
    for key in ("price", "avg_price", "cost", "per_capita"):
        value = (item.metadata or {}).get(key)
        if value not in (None, ""):
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
    return default


def _safe_time(value: str) -> str:
    try:
        time_to_minutes(value)
        return value
    except Exception:
        return "09:00"
