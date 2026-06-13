"""POI ranking: hard filtering + preference score + MMR diversity."""

from __future__ import annotations

import math
from typing import Any

from src.data_layer.schema import Constraints, GroundedPreferences, POICandidate


def rank_pois(
    pois: list[dict[str, Any]],
    preferences: GroundedPreferences,
    top_k: int = 50,
    must_visit_ids: set[str] | None = None,
    constraints: Constraints | None = None,
) -> list[POICandidate]:
    """Rank attractions and keep a diverse top-k candidate set.

    Must-visit POIs get very high priority with fuzzy/substring matching.
    If a must_visit name doesn't exactly match any candidate, we fuzzy-search
    across all POI names and boost the closest match.
    """
    if not pois:
        return []

    must_visit_ids = must_visit_ids or set()
    required_types, forbidden_types, forbidden_names = _extract_type_constraints(constraints)

    # --- fuzzy match must_visit names against all candidates ---
    fuzzy_matched: dict[str, str] = {}  # must_visit_name -> best_poi_id
    for mv_name in list(must_visit_ids):
        if any(_poi_id(p) == mv_name for p in pois):
            continue  # exact match exists
        if any(str(p.get("name", "")) == mv_name for p in pois):
            continue  # exact name match exists
        # try fuzzy: substring or partial match
        best_score = 0.0
        best_id = ""
        mv_lower = mv_name.lower()
        for p in pois:
            p_name = str(p.get("name", ""))
            p_id = _poi_id(p)
            # score: exact substring > shared words > character overlap
            if mv_lower in p_name.lower():
                score = len(mv_lower) / max(len(p_name), 1)
            elif p_name.lower() in mv_lower:
                score = len(p_name) / max(len(mv_lower), 1)
            else:
                # word-level overlap
                mv_words = set(mv_lower.split())
                p_words = set(p_name.lower().split())
                overlap = len(mv_words & p_words)
                if overlap > 0:
                    score = overlap / max(len(mv_words), 1) * 0.5
                else:
                    continue
            if score > best_score:
                best_score = score
                best_id = p_id
        if best_score > 0.3 and best_id:
            fuzzy_matched[mv_name] = best_id

    scored: list[tuple[float, dict[str, Any]]] = []
    for poi in pois:
        poi_id = _poi_id(poi)
        name = str(poi.get("name", ""))
        if _is_forbidden_poi(poi, forbidden_types, forbidden_names):
            continue
        base = _base_poi_score(poi, preferences, name, poi_id)
        if poi_id in must_visit_ids or name in must_visit_ids:
            base += 1000.0
        if poi_id in fuzzy_matched.values() or any(
            poi_id == fid for fid in fuzzy_matched.values()
        ):
            base += 800.0  # fuzzy matched must_visit, slightly lower than exact
        if required_types and _matches_any_type(poi, required_types):
            base += 500.0
        scored.append((base, poi))

    scored.sort(key=lambda x: -x[0])

    selected: list[POICandidate] = []
    selected_regions: list[str] = []
    lambda_mmr = 0.7

    while scored and len(selected) < top_k:
        best_idx = 0
        best_mmr = -math.inf
        for idx, (rel_score, poi) in enumerate(scored):
            region = _region_of(poi)
            same_region_ratio = 0.0
            if selected_regions:
                same_region_ratio = sum(1 for r in selected_regions if r == region) / len(selected_regions)
            mmr = lambda_mmr * rel_score - (1 - lambda_mmr) * same_region_ratio * rel_score
            if mmr > best_mmr:
                best_mmr = mmr
                best_idx = idx
        _, chosen = scored.pop(best_idx)
        region = _region_of(chosen)
        selected_regions.append(region)
        selected.append(POICandidate(
            poi_id=_poi_id(chosen), name=str(chosen.get("name", "")),
            score=round(best_mmr, 4), region=region, metadata=dict(chosen),
        ))
    return selected


def _extract_type_constraints(
    constraints: Constraints | None,
) -> tuple[list[str], list[str], list[str]]:
    if constraints is None:
        return [], [], []
    required: list[str] = []
    forbidden_types: list[str] = []
    forbidden_names: list[str] = []
    for card in constraints.cards:
        if card.category != "attraction":
            continue
        params = card.parameters or {}
        if params.get("must_visit_type"):
            required.append(str(params["must_visit_type"]))
        if params.get("forbidden_attraction_type"):
            forbidden_types.append(str(params["forbidden_attraction_type"]))
        if params.get("forbidden_poi"):
            forbidden_names.append(str(params["forbidden_poi"]))
    return required, forbidden_types, forbidden_names


def _poi_id(poi: dict[str, Any]) -> str:
    for key in ("id", "poi_id", "uid", "name"):
        if poi.get(key):
            return str(poi[key])
    return "unknown"


def _region_of(poi: dict[str, Any]) -> str:
    for key in ("region", "district", "area"):
        if poi.get(key):
            return str(poi[key])
    name = str(poi.get("name", ""))
    return name[:2] if len(name) >= 2 else "default"


def _poi_type(poi: dict[str, Any]) -> str:
    return str(poi.get("type") or poi.get("category") or poi.get("tags") or "")


def _matches_type(poi: dict[str, Any], wanted: str) -> bool:
    wanted_l = wanted.lower()
    type_l = _poi_type(poi).lower()
    name_l = str(poi.get("name", "")).lower()
    return wanted_l in type_l or type_l in wanted_l or wanted_l in name_l


def _matches_any_type(poi: dict[str, Any], wanted_types: list[str]) -> bool:
    return any(_matches_type(poi, t) for t in wanted_types)


def _is_forbidden_poi(
    poi: dict[str, Any],
    forbidden_types: list[str],
    forbidden_names: list[str],
) -> bool:
    name_l = str(poi.get("name", "")).lower()
    if any(n.lower() in name_l for n in forbidden_names):
        return True
    return any(_matches_type(poi, t) for t in forbidden_types)


def _base_poi_score(
    poi: dict[str, Any],
    preferences: GroundedPreferences,
    name: str,
    poi_id: str,
) -> float:
    score = 1.0

    for key, weight in preferences.poi_weights.items():
        if key and (key in name or key == poi_id):
            score += float(weight)

    rating = poi.get("rating") or poi.get("score")
    if rating is not None:
        try:
            score += float(rating) * 0.5
        except (TypeError, ValueError):
            pass

    popularity = poi.get("popularity")
    if popularity is not None:
        try:
            score += float(popularity) * 0.3
        except (TypeError, ValueError):
            pass

    price = poi.get("price") or poi.get("cost") or 0
    try:
        if float(price) == 0:
            score += preferences.budget_weight * 0.2
        elif preferences.budget_weight > 0.7:
            score -= min(1.0, float(price) / 200.0)
    except (TypeError, ValueError):
        pass

    return score
