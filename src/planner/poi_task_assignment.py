"""Multi-day POI task assignment with policy-aware priorities."""

from __future__ import annotations

from src.data_layer.schema import CandidatePool, Constraints, DayAssignment, POICandidate, Plan
from src.planner.constraint_profile import extract_planning_constraints
from src.skills.lock_must_visit import lock_must_visit_order


def allocate_pois_to_days(
    constraints: Constraints,
    candidates: CandidatePool,
    policy: str = "safe",
) -> Plan:
    """Create a coarse day assignment with must-visit enforcement.

    Must-visit POIs are forced into day assignments first (at least one per day
    if possible), then remaining capacity is filled with highest-scoring others.
    Must-visit POIs CANNOT be dropped by ordinary budget/route optimization.
    """
    pc = extract_planning_constraints(constraints)
    pois = [p for p in (candidates.pois or []) if _allowed(p, pc)]
    must = [p for p in pois if _is_must(p, pc)]
    others = [p for p in pois if p not in must]
    if policy == "budget":
        others.sort(key=lambda p: _price(p))
    else:
        others.sort(key=lambda p: -p.score)
    # fuzzy match: if pc.must_visit has names not in candidates, search across all
    for mv_name in pc.must_visit:
        if not any(_is_must(p, pc) for p in pois if mv_name.lower() in p.name.lower()):
            # try to find a fuzzy match in all candidates
            for p in pois:
                if mv_name.lower() in p.name.lower() or p.name.lower() in mv_name.lower():
                    if p not in must:
                        must.append(p)
                    break

    ordered = _dedupe(must + others)
    lock_result = lock_must_visit_order(ordered, pc.must_visit, pc.must_visit_types)
    ordered_ids = lock_result.decision.get("ordered_poi_ids") or []
    if ordered_ids:
        by_id = {p.poi_id: p for p in ordered}
        reordered = [by_id[pid] for pid in ordered_ids if pid in by_id]
        if len(reordered) == len(ordered):
            ordered = reordered

    # Force at least one must-visit per day if possible
    must_ids = {p.poi_id for p in must}
    must_ordered = [p for p in ordered if p.poi_id in must_ids]
    non_must_ordered = [p for p in ordered if p.poi_id not in must_ids]

    assignments: list[DayAssignment] = []
    must_idx = 0
    other_idx = 0
    for day_idx in range(pc.days):
        cap = _capacity(policy, pc, day_idx == pc.days - 1)
        day_ids: list[str] = []
        # Assign at least one must_visit per day (if still available)
        if must_idx < len(must_ordered):
            day_ids.append(must_ordered[must_idx].poi_id)
            must_idx += 1
            cap -= 1
        # Fill remaining capacity: prioritize remaining must, then others
        while cap > 0:
            if must_idx < len(must_ordered):
                day_ids.append(must_ordered[must_idx].poi_id)
                must_idx += 1
            elif other_idx < len(non_must_ordered):
                day_ids.append(non_must_ordered[other_idx].poi_id)
                other_idx += 1
            else:
                break
            cap -= 1
        # If last day and there are remaining must_visit, cram them in
        if day_idx == pc.days - 1:
            while must_idx < len(must_ordered):
                day_ids.append(must_ordered[must_idx].poi_id)
                must_idx += 1
        assignments.append(DayAssignment(day_index=day_idx, date=f"Day{day_idx + 1}", poi_ids=day_ids))

    return Plan(
        query_id=constraints.query_id,
        policy=policy,
        day_assignments=assignments,
        metadata={"stage": "allocated", "assignment_policy": policy},
    )


def _capacity(policy: str, pc, is_final_day: bool) -> int:
    if pc.max_pois_per_day:
        cap = pc.max_pois_per_day
    elif policy == "safe" or pc.pace == "relaxed":
        cap = 2
    elif policy == "preference" or pc.pace == "intensive":
        cap = 4
    else:
        cap = 3
    if policy == "budget":
        cap = min(cap, 2)
    if is_final_day:
        cap = max(1, cap - 1)
    return max(1, cap)


def _allowed(poi: POICandidate, pc) -> bool:
    name_l = poi.name.lower()
    ptype = str((poi.metadata or {}).get("type", "")).lower()
    if any(f.lower() in name_l for f in pc.forbidden_pois):
        return False
    return not any(f.lower() in ptype or f.lower() in name_l for f in pc.forbidden_attraction_types)


def _is_must(poi: POICandidate, pc) -> bool:
    name_l = poi.name.lower()
    pid_l = poi.poi_id.lower()
    ptype = str((poi.metadata or {}).get("type", "")).lower()
    return any(m.lower() in name_l or m.lower() == pid_l for m in pc.must_visit) or any(
        t.lower() in ptype or t.lower() in name_l for t in pc.must_visit_types
    )


def _price(poi: POICandidate) -> float:
    for key in ("price", "cost"):
        value = (poi.metadata or {}).get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
    return 0.0


def _dedupe(items: list[POICandidate]) -> list[POICandidate]:
    seen: set[str] = set()
    out: list[POICandidate] = []
    for item in items:
        key = item.poi_id or item.name
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
