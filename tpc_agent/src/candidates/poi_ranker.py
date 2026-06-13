"""POI 排序：Top-K + MMR 多样性选择。"""

from __future__ import annotations

import math
from typing import Any

from src.data_layer.schema import GroundedPreferences, POICandidate


def rank_pois(
    pois: list[dict[str, Any]],
    preferences: GroundedPreferences,
    top_k: int = 50,
    must_visit_ids: set[str] | None = None,
) -> list[POICandidate]:
    """对景点 POI 打分排序，并用 MMR 保证区域多样性。

    评分因素：
        1. preferences.poi_weights 中按名称/id 的权重；
        2. POI 自身 rating / popularity（若有）；
        3. 必去景点强制置顶；
        4. MMR 惩罚同 region 过度集中。

    Args:
        pois: 原始 POI 字典列表。
        preferences: 语义落地偏好权重。
        top_k: 保留数量。
        must_visit_ids: 必去 POI ID 集合，保证进入候选池。

    Returns:
        list[POICandidate]: 排序后候选，长度 <= top_k。
    """
    if not pois:
        return []

    must_visit_ids = must_visit_ids or set()
    scored: list[tuple[float, dict[str, Any]]] = []

    for poi in pois:
        poi_id = _poi_id(poi)
        name = str(poi.get("name", ""))
        base = _base_poi_score(poi, preferences, name, poi_id)
        if poi_id in must_visit_ids:
            base += 1000.0  # 必去项绝对优先
        scored.append((base, poi))

    scored.sort(key=lambda x: -x[0])

    # MMR 选择：在高分 POI 中避免同一 region 过度堆叠
    selected: list[POICandidate] = []
    selected_regions: list[str] = []
    lambda_mmr = 0.7

    while scored and len(selected) < top_k:
        best_idx = 0
        best_mmr = -math.inf

        for idx, (rel_score, poi) in enumerate(scored):
            region = _region_of(poi)
            diversity_penalty = 0.0
            if selected_regions:
                same = sum(1 for r in selected_regions if r == region)
                diversity_penalty = same / len(selected_regions)
            mmr = lambda_mmr * rel_score - (1 - lambda_mmr) * diversity_penalty * rel_score
            if mmr > best_mmr:
                best_mmr = mmr
                best_idx = idx

        _, chosen = scored.pop(best_idx)
        region = _region_of(chosen)
        selected_regions.append(region)
        selected.append(
            POICandidate(
                poi_id=_poi_id(chosen),
                name=str(chosen.get("name", "")),
                score=round(best_mmr, 4),
                region=region,
                metadata=dict(chosen),
            )
        )

    return selected


def _poi_id(poi: dict[str, Any]) -> str:
    """提取 POI 唯一 ID。"""
    for key in ("id", "poi_id", "uid", "name"):
        if poi.get(key):
            return str(poi[key])
    return "unknown"


def _region_of(poi: dict[str, Any]) -> str:
    """提取或推断 POI 所属区域（用于 MMR 多样性）。"""
    for key in ("region", "district", "area"):
        if poi.get(key):
            return str(poi[key])
    # 无区域字段时用名称前两字作为粗粒度区域
    name = str(poi.get("name", ""))
    return name[:2] if len(name) >= 2 else "default"


def _base_poi_score(
    poi: dict[str, Any],
    preferences: GroundedPreferences,
    name: str,
    poi_id: str,
) -> float:
    """计算 POI 基础相关度分数。"""
    score = 1.0

    # 偏好权重表匹配
    for key, weight in preferences.poi_weights.items():
        if key in name or key == poi_id:
            score += float(weight)

    # 评分 / 热度
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

    # 免费景点在预算紧张时略加分（由 pace/budget 权重间接体现）
    price = poi.get("price") or poi.get("cost") or 0
    try:
        if float(price) == 0:
            score += preferences.budget_weight * 0.2
    except (TypeError, ValueError):
        pass

    return score
