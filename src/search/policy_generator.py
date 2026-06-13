"""Policy generation for best-of-N planning."""

from __future__ import annotations

from src.data_layer.schema import Constraints
from src.planner.constraint_profile import extract_planning_constraints


BASE_POLICIES = ["safe", "budget", "preference", "low_transport", "must_visit_first"]


def generate_policies(
    constraints: Constraints,
    base_policies: list[str] | None = None,
) -> list[str]:
    """Generate policy order from constraint features."""
    pc = extract_planning_constraints(constraints)
    ordered: list[str] = []

    if pc.must_visit or pc.must_visit_types:
        ordered.append("must_visit_first")
    if pc.total_budget is not None or pc.dining_budget is not None or pc.accommodation_budget is not None:
        ordered.append("budget")
    if pc.pace == "relaxed":
        ordered.append("safe")
    if pc.pace == "intensive" or pc.must_visit_types or pc.cuisine_preferences:
        ordered.append("preference")
    if pc.hotel_near_anchor or "metro" in pc.innercity_modes:
        ordered.append("low_transport")

    ordered.extend(base_policies or BASE_POLICIES)
    ordered.extend(BASE_POLICIES)
    return _dedupe(ordered)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out
