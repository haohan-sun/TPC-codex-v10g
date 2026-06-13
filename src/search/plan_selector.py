"""Candidate plan selection."""

from __future__ import annotations

from src.skills.plan_selector_best_of_n import plan_selector_best_of_n


def select_best_plan(
    candidates: list[tuple[object, float, str]],
) -> tuple:
    """Select the best plan from (plan, score, policy) candidates."""
    if not candidates:
        raise ValueError("select_best_plan requires at least one candidate")
    result = plan_selector_best_of_n({"candidates": candidates})
    idx = int(result.decision.get("selected_index", 0))
    plan, score, policy = candidates[idx]
    if isinstance(plan, dict):
        return plan, score, policy
    return plan, score
