"""Daily attraction ordering skill that preserves meal/hotel anchors."""

from __future__ import annotations

from typing import Any

from src.optimizer.two_opt import two_opt
from src.skills.skill_types import SkillContext, SkillResult


def order_daily_route_with_meals(
    payload: dict[str, Any],
    context: SkillContext | None = None,
) -> SkillResult:
    """Order attraction positions using a local distance matrix.

    The caller owns the schedule structure.  This skill only returns the ordered
    attraction names, so meals/hotel/intercity activities stay anchored.
    """
    attractions = payload.get("attractions") or []
    names = [
        str(a.get("position") if isinstance(a, dict) else a)
        for a in attractions
        if str(a.get("position") if isinstance(a, dict) else a)
    ]
    matrix = payload.get("distance_matrix") or {}
    start_anchor = str(payload.get("start_anchor") or "")

    if len(names) <= 1:
        ordered = names
    else:
        ordered = _nearest_neighbor(names, matrix, start_anchor)
        ordered = two_opt(ordered, matrix)

    return SkillResult(
        name="order_daily_route_with_meals",
        category="schedule",
        decision={"ordered_positions": ordered, "preserved_anchors": True},
        score=_route_cost(ordered, matrix),
        evidence=ordered,
    )


def order_attraction_names(
    names: list[str],
    matrix: dict[tuple[str, str], float],
    start_anchor: str = "",
) -> SkillResult:
    return order_daily_route_with_meals({
        "attractions": names,
        "distance_matrix": matrix,
        "start_anchor": start_anchor,
    })


def _nearest_neighbor(
    names: list[str],
    matrix: dict[tuple[str, str], float],
    start_anchor: str,
) -> list[str]:
    unvisited = set(names)
    current = start_anchor or names[0]
    route: list[str] = []
    while unvisited:
        nxt = min(unvisited, key=lambda n: matrix.get((current, n), matrix.get((n, current), 9999.0)))
        route.append(nxt)
        unvisited.remove(nxt)
        current = nxt
    return route


def _route_cost(route: list[str], matrix: dict[tuple[str, str], float]) -> float:
    total = 0.0
    for a, b in zip(route, route[1:]):
        total += float(matrix.get((a, b), matrix.get((b, a), 0.0)))
    return round(total, 4)
