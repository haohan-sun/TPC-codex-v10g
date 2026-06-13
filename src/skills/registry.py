"""Skill registry for offline local travel-planning decisions."""

from __future__ import annotations

from typing import Any

from src.skills.skill_types import SkillContext, SkillResult, SkillSpec


_REGISTRY: dict[str, SkillSpec] = {}
_BUILTINS_LOADED = False


def register_skill(spec: SkillSpec) -> SkillSpec:
    """Register or replace a skill spec by name."""
    _REGISTRY[spec.name] = spec
    return spec


def get_skill(name: str) -> SkillSpec:
    """Return a registered skill, loading builtins on first use."""
    register_builtin_skills()
    if name not in _REGISTRY:
        raise KeyError(f"skill not registered: {name}")
    return _REGISTRY[name]


def list_skills(category: str | None = None) -> list[SkillSpec]:
    """List registered skills, optionally filtered by category."""
    register_builtin_skills()
    specs = list(_REGISTRY.values())
    if category is not None:
        specs = [s for s in specs if s.category == category]
    return sorted(specs, key=lambda s: (s.category, s.name))


def call_skill(
    name: str,
    payload: dict[str, Any],
    context: SkillContext | None = None,
) -> SkillResult:
    """Call a registered skill with a dict payload and optional context."""
    spec = get_skill(name)
    return spec.fn(payload, context)


def register_builtin_skills() -> None:
    """Register the built-in local skills once.

    Imports stay inside this function so regular module imports do not create
    stage-level cycles.
    """
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return
    _BUILTINS_LOADED = True

    from src.skills.choose_hotel_anchor import choose_hotel_anchor_skill
    from src.skills.cross_city_day_light_plan import cross_city_day_light_plan
    from src.skills.ground_travel_intent import ground_travel_intent
    from src.skills.insert_meals import insert_meals_by_route
    from src.skills.lock_must_visit import lock_must_visit_skill
    from src.skills.order_daily_route_with_meals import order_daily_route_with_meals
    from src.skills.plan_selector_best_of_n import plan_selector_best_of_n
    from src.skills.repair_by_typed_error import repair_by_typed_error

    register_skill(SkillSpec(
        name="ground_travel_intent",
        category="semantic",
        phase="semantic_grounding",
        fn=ground_travel_intent,
        input_keys=("constraints", "active_info", "nl_text"),
        output_keys=("planning_hints", "poi_weights", "tags"),
        description="Ground natural language preferences into planner hints.",
    ))
    register_skill(SkillSpec(
        name="choose_hotel_anchor",
        category="schedule",
        phase="hotel_selection",
        fn=choose_hotel_anchor_skill,
        input_keys=("hotels", "pois", "constraints"),
        output_keys=("hotel_id", "hotel_name", "anchor"),
        description="Pick a hotel anchor under budget, type, and distance hints.",
    ))
    register_skill(SkillSpec(
        name="insert_meals_by_route",
        category="schedule",
        phase="meal_insertion",
        fn=insert_meals_by_route,
        input_keys=("day_activities", "restaurants"),
        output_keys=("meal_choices", "patches"),
        description="Choose missing meals along a day route without duplicating restaurants.",
    ))
    register_skill(SkillSpec(
        name="lock_must_visit",
        category="planning",
        phase="task_assignment",
        fn=lock_must_visit_skill,
        input_keys=("pois", "must_visit", "must_visit_types"),
        output_keys=("ordered_poi_ids", "locked_ids", "missing"),
        description="Lock must-visit POIs before soft-preference assignment.",
    ))
    register_skill(SkillSpec(
        name="cross_city_day_light_plan",
        category="planning",
        phase="rolling_day_planning",
        fn=cross_city_day_light_plan,
        input_keys=("arrival_time", "departure_time", "policy"),
        output_keys=("light_day", "allowed_pois", "skip_meals"),
        description="Constrain days with late arrival or early departure to a light plan.",
    ))
    register_skill(SkillSpec(
        name="order_daily_route_with_meals",
        category="schedule",
        phase="day_route_optimization",
        fn=order_daily_route_with_meals,
        input_keys=("attractions", "distance_matrix", "start_anchor"),
        output_keys=("ordered_positions",),
        description="Order daily attractions while preserving meal/hotel anchors.",
    ))
    register_skill(SkillSpec(
        name="repair_by_typed_error",
        category="repair",
        phase="typed_repair",
        fn=repair_by_typed_error,
        input_keys=("error", "plan_slice"),
        output_keys=("patches",),
        description="Map verifier error types to local repair patches.",
    ))
    register_skill(SkillSpec(
        name="plan_selector_best_of_n",
        category="planning",
        phase="candidate_selection",
        fn=plan_selector_best_of_n,
        input_keys=("candidates",),
        output_keys=("selected_index", "policy", "adjusted_score"),
        description="Select the best candidate plan from verifier/local scores.",
    ))
