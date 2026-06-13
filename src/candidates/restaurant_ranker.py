"""Restaurant ranking with cuisine preference and dining budget."""

from __future__ import annotations

from typing import Any

from src.data_layer.schema import Constraints, GroundedPreferences, POICandidate


def rank_restaurants(
    restaurants: list[dict[str, Any]],
    preferences: GroundedPreferences,
    constraints: Constraints | None = None,
    top_k: int = 30,
) -> list[POICandidate]:
    if not restaurants:
        return []

    dining_budget = _budget_limit(constraints, "dining")
    required, forbidden = _cuisine_constraints(constraints)
    required_names = _restaurant_name_constraints(constraints)
    people = int((constraints.global_params.get("people_number") if constraints else None) or 1)
    days = int((constraints.global_params.get("days") if constraints else None) or 1)
    meal_count = max(1, days * 3 - 1)
    per_meal_budget = dining_budget / (meal_count * people) if dining_budget else None

    scored: list[tuple[float, dict[str, Any]]] = []
    for rest in restaurants:
        if _matches_any(rest, forbidden):
            continue
        if required and not _matches_any(rest, required):
            continue

        price = _float_price(rest)
        score = 1.0
        name = str(rest.get("name", ""))
        cuisine = str(rest.get("cuisine", rest.get("type", "")))

        for tag, weight in preferences.cuisine_weights.items():
            if tag.lower() in name.lower() or tag.lower() in cuisine.lower():
                score += float(weight)

        for tag in required:
            if _matches_any(rest, [tag]):
                score += 2.0

        if required_names and _matches_restaurant_name(rest, required_names):
            score += 1000.0

        if preferences.tags.get("cuisine_preference") == "local":
            if _looks_local(rest):
                score += 0.8

        if per_meal_budget is not None:
            if price <= per_meal_budget:
                score += 1.2
            elif price <= per_meal_budget * 1.5:
                score += 0.3
            else:
                score -= min(2.0, (price - per_meal_budget) / max(per_meal_budget, 1.0))
        else:
            score += max(0.0, 1.0 - price / 250.0)

        rating = rest.get("rating") or rest.get("score")
        if rating is not None:
            try:
                score += float(rating) * 0.3
            except (TypeError, ValueError):
                pass

        scored.append((score, rest))

    scored.sort(key=lambda x: (-x[0], _float_price(x[1])))
    return [
        POICandidate(
            poi_id=_rest_id(rest),
            name=str(rest.get("name", "")),
            score=round(score, 4),
            region=str(rest.get("region", rest.get("district", ""))),
            metadata=dict(rest),
        )
        for score, rest in scored[:top_k]
    ]


def _budget_limit(constraints: Constraints | None, budget_type: str) -> float | None:
    if constraints is None:
        return None
    for card in constraints.cards:
        if card.category == "budget" and card.parameters.get("budget_type") == budget_type:
            val = card.parameters.get("max_cost")
            if val is not None:
                return float(val)
    return None


def _cuisine_constraints(constraints: Constraints | None) -> tuple[list[str], list[str]]:
    required: list[str] = []
    forbidden: list[str] = []
    if constraints is None:
        return required, forbidden
    for card in constraints.cards:
        params = card.parameters or {}
        if card.category == "dietary" and params.get("cuisine_preference"):
            required.append(str(params["cuisine_preference"]))
        if card.category == "dietary" and params.get("forbidden_cuisine"):
            forbidden.append(str(params["forbidden_cuisine"]))
    return required, forbidden


def _restaurant_name_constraints(constraints: Constraints | None) -> list[str]:
    if constraints is None:
        return []
    names: list[str] = []
    for card in constraints.cards:
        params = card.parameters or {}
        if card.category == "dietary" and params.get("restaurant_name"):
            names.append(str(params["restaurant_name"]))
    return names


def _matches_any(rest: dict[str, Any], values: list[str]) -> bool:
    haystack = " ".join(str(rest.get(k, "")) for k in ("name", "cuisine", "type", "recommendedfood")).lower()
    hay_norm = _norm_text(haystack)
    return any(v.lower() in haystack or _norm_text(v) in hay_norm for v in values)


def _matches_restaurant_name(rest: dict[str, Any], names: list[str]) -> bool:
    rest_name = str(rest.get("name", ""))
    rest_norm = _norm_text(rest_name)
    return any(name.lower() in rest_name.lower() or _norm_text(name) == rest_norm for name in names)


def _norm_text(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _looks_local(rest: dict[str, Any]) -> bool:
    haystack = " ".join(str(rest.get(k, "")) for k in ("name", "cuisine", "recommendedfood")).lower()
    return any(k in haystack for k in ("local", "sichuan", "cuisine", "tea", "hotpot", "老字号", "特色"))


def _rest_id(rest: dict[str, Any]) -> str:
    for key in ("id", "poi_id", "uid", "name"):
        if rest.get(key):
            return str(rest[key])
    return "unknown"


def _float_price(record: dict[str, Any]) -> float:
    for key in ("price", "avg_price", "cost", "per_capita"):
        if record.get(key) is not None:
            try:
                return float(record[key])
            except (TypeError, ValueError):
                pass
    return 50.0
