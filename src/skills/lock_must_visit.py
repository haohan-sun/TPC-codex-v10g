"""Lock must-visit POIs before softer route/task decisions."""

from __future__ import annotations

from typing import Any

from src.data_layer.schema import Plan, POICandidate
from src.skills.skill_types import SkillContext, SkillResult


def lock_must_visit_skill(
    payload: dict[str, Any],
    context: SkillContext | None = None,
) -> SkillResult:
    pois = list(payload.get("pois") or [])
    must_visit = [str(x) for x in payload.get("must_visit") or []]
    must_visit_types = [str(x) for x in payload.get("must_visit_types") or []]

    locked: list[POICandidate] = []
    remaining: list[POICandidate] = []
    missing = set(must_visit)

    for poi in pois:
        if _is_must(poi, must_visit, must_visit_types):
            locked.append(poi)
            _mark_matched(missing, poi)
        else:
            remaining.append(poi)

    ordered = _dedupe(locked + remaining)
    return SkillResult(
        name="lock_must_visit",
        category="planning",
        decision={
            "ordered_poi_ids": [p.poi_id for p in ordered],
            "locked_ids": [p.poi_id for p in _dedupe(locked)],
            "missing": sorted(missing),
        },
        score=float(len(locked)),
        evidence=[p.name for p in locked],
        warnings=[f"missing must_visit: {m}" for m in sorted(missing)],
    )


def lock_must_visit_order(
    pois: list[POICandidate],
    must_visit: list[str],
    must_visit_types: list[str] | None = None,
) -> SkillResult:
    """Convenience helper for planner task allocation."""
    return lock_must_visit_skill({
        "pois": pois,
        "must_visit": must_visit,
        "must_visit_types": must_visit_types or [],
    })


def lock_must_visit(plan: Plan, must_visit_ids: list[str]) -> Plan:
    """Compatibility wrapper: ensure must IDs appear in earliest assignments."""
    if not plan.day_assignments:
        return plan
    seen = {pid for d in plan.day_assignments for pid in d.poi_ids}
    missing = [pid for pid in must_visit_ids if pid not in seen]
    if missing:
        first = plan.day_assignments[0]
        first.poi_ids = _dedupe_ids(missing + first.poi_ids)
    plan.metadata["skill_lock_must_visit"] = {
        "locked_ids": must_visit_ids,
        "inserted_missing": missing,
    }
    return plan


def _is_must(poi: POICandidate, must_visit: list[str], must_visit_types: list[str]) -> bool:
    name_l = poi.name.lower()
    pid_l = poi.poi_id.lower()
    ptype = str((poi.metadata or {}).get("type", "")).lower()
    return any(m.lower() in name_l or m.lower() == pid_l for m in must_visit) or any(
        t.lower() in ptype or t.lower() in name_l for t in must_visit_types
    )


def _mark_matched(missing: set[str], poi: POICandidate) -> None:
    for item in list(missing):
        item_l = item.lower()
        if item_l in poi.name.lower() or item_l == poi.poi_id.lower():
            missing.discard(item)


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


def _dedupe_ids(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out
