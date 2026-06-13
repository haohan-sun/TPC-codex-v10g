"""Multi-candidate search over planning policies."""

from __future__ import annotations

from typing import Callable

from src.data_layer.schema import CandidatePool, Constraints, OfficialPlan, Query
from src.search.plan_selector import select_best_plan


def multi_candidate_search(
    query: Query,
    constraints: Constraints,
    candidates: CandidatePool,
    plan_builder: Callable[..., OfficialPlan | tuple[OfficialPlan, float]],
    policies: list[str],
) -> tuple[OfficialPlan, float]:
    """Generate candidates for multiple policies and select the best one."""
    results: list[tuple[OfficialPlan, float, str]] = []
    for policy in policies:
        built = _call_builder(plan_builder, query, constraints, candidates, policy)
        if isinstance(built, tuple):
            plan, score = built
        else:
            plan, score = built, 0.0
        results.append((plan, float(score), policy))
    return select_best_plan(results)


def _call_builder(
    plan_builder: Callable,
    query: Query,
    constraints: Constraints,
    candidates: CandidatePool,
    policy: str,
):
    try:
        return plan_builder(
            query=query,
            constraints=constraints,
            candidates=candidates,
            policy=policy,
        )
    except TypeError:
        try:
            return plan_builder(query, constraints, candidates, policy)
        except TypeError:
            return plan_builder(policy)
