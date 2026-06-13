"""Cross-city arrival/departure day planning skill."""

from __future__ import annotations

from typing import Any

from src.planner.plan_utils import time_to_minutes
from src.skills.skill_types import SkillContext, SkillResult


def cross_city_day_light_plan(
    payload: dict[str, Any],
    context: SkillContext | None = None,
) -> SkillResult:
    """Decide whether a cross-city day should be deliberately light."""
    arrival_time = str(payload.get("arrival_time") or "")
    departure_time = str(payload.get("departure_time") or "")
    policy = str(payload.get("policy") or (context.policy if context else "safe"))
    poi_count = int(payload.get("poi_count") or 0)

    light_day = False
    allowed_pois = poi_count
    skip_meals: list[str] = []
    reasons: list[str] = []

    arrival_min = _minutes_or_none(arrival_time)
    departure_min = _minutes_or_none(departure_time)

    if arrival_min is not None:
        if arrival_min >= time_to_minutes("19:00"):
            light_day = True
            allowed_pois = 0
            skip_meals.extend(["breakfast", "lunch", "dinner"])
            reasons.append("late arrival after 19:00")
        elif arrival_min >= time_to_minutes("17:30"):
            light_day = True
            allowed_pois = 1 if policy in {"preference", "must_visit_first"} else 0
            skip_meals.extend(["breakfast", "lunch"])
            reasons.append("evening arrival")
        elif arrival_min >= time_to_minutes("13:30"):
            light_day = policy == "safe"
            allowed_pois = min(poi_count, 1 if policy == "safe" else 2)
            skip_meals.append("breakfast")
            reasons.append("afternoon arrival")

    if departure_min is not None:
        if departure_min <= time_to_minutes("12:00"):
            light_day = True
            allowed_pois = 0
            skip_meals.extend(["lunch", "dinner"])
            reasons.append("morning departure")
        elif departure_min <= time_to_minutes("16:00"):
            light_day = True
            allowed_pois = min(allowed_pois, 1)
            skip_meals.append("dinner")
            reasons.append("early return departure")

    skip_meals = sorted(set(skip_meals), key=("breakfast", "lunch", "dinner").index)
    return SkillResult(
        name="cross_city_day_light_plan",
        category="planning",
        decision={
            "light_day": light_day,
            "allowed_pois": max(0, allowed_pois),
            "skip_meals": skip_meals,
            "reason": "; ".join(reasons) if reasons else "normal day capacity",
        },
        score=1.0 if light_day else 0.0,
        evidence=reasons,
    )


def _minutes_or_none(value: str) -> int | None:
    if not value:
        return None
    try:
        return time_to_minutes(value)
    except Exception:
        return None
