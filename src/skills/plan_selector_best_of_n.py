"""Best-of-N candidate plan selection skill."""

from __future__ import annotations

from typing import Any

from src.skills.skill_types import SkillContext, SkillResult


POLICY_TIEBREAK = {
    "must_visit_first": 0.04,
    "preference": 0.03,
    "safe": 0.02,
    "budget": 0.01,
    "low_transport": 0.0,
}


def plan_selector_best_of_n(
    payload: dict[str, Any],
    context: SkillContext | None = None,
) -> SkillResult:
    """Select the strongest candidate using verifier score plus stable ties."""
    candidates = list(payload.get("candidates") or [])
    if not candidates:
        return SkillResult(
            name="plan_selector_best_of_n",
            category="planning",
            warnings=["no candidate plans"],
        )

    scored: list[tuple[float, int, str, float]] = []
    for idx, item in enumerate(candidates):
        plan, raw_score, policy = _unpack(item)
        adjusted = float(raw_score)
        adjusted += POLICY_TIEBREAK.get(policy, 0.0)
        if _itinerary_len(plan) <= 0:
            adjusted -= 1000.0
        scored.append((adjusted, idx, policy, float(raw_score)))

    scored.sort(key=lambda row: (-row[0], row[1]))
    adjusted, idx, policy, raw = scored[0]
    return SkillResult(
        name="plan_selector_best_of_n",
        category="planning",
        decision={
            "selected_index": idx,
            "policy": policy,
            "raw_score": raw,
            "adjusted_score": adjusted,
            "candidate_count": len(candidates),
        },
        score=adjusted,
        evidence=[f"{policy}:{raw}"],
    )


def _unpack(item: Any) -> tuple[Any, float, str]:
    if isinstance(item, dict):
        return item.get("plan"), float(item.get("score", 0.0)), str(item.get("policy", ""))
    plan, score, policy = item
    return plan, float(score), str(policy)


def _itinerary_len(plan: Any) -> int:
    payload = getattr(plan, "itinerary", plan)
    if isinstance(payload, dict):
        itinerary = payload.get("itinerary")
        return len(itinerary) if isinstance(itinerary, list) else 0
    return 0
