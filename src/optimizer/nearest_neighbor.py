"""最近邻启发式。"""

from __future__ import annotations

from typing import Any


def nearest_neighbor_route(
    poi_ids: list[str],
    distance_matrix: dict[str, Any],
    start_id: str | None = None,
) -> list[str]:
    """最近邻构建初始路线。

    Args:
        poi_ids: POI ID 列表。
        distance_matrix: 距离/时间矩阵。
        start_id: 起点 ID，默认为第一个 POI。

    Returns:
        list[str]: 排序后 POI ID。
    """
    if len(poi_ids) <= 1:
        return list(poi_ids)

    _dm = _normalize_matrix(distance_matrix)
    unvisited = set(poi_ids)
    route: list[str] = []

    current = start_id if start_id and start_id in unvisited else poi_ids[0]
    route.append(current)
    unvisited.discard(current)

    while unvisited:
        best_next: str | None = None
        best_dist: float = float("inf")

        for nxt in unvisited:
            d = _lookup(current, nxt, _dm)
            if d < best_dist:
                best_dist = d
                best_next = nxt

        if best_next is None:
            # 兜底：选第一个未访问的
            best_next = next(iter(unvisited))

        route.append(best_next)
        unvisited.discard(best_next)
        current = best_next

    return route


def _normalize_matrix(dm: dict[str, Any]) -> dict[tuple[str, str], float]:
    """将各种键格式统一为 (str, str) -> float。"""
    out: dict[tuple[str, str], float] = {}
    for k, v in dm.items():
        if isinstance(k, tuple) and len(k) == 2:
            out[(str(k[0]), str(k[1]))] = float(v)
        elif isinstance(k, str):
            # 尝试解析 "a->b" 格式
            parts = k.split("->")
            if len(parts) == 2:
                out[(parts[0].strip(), parts[1].strip())] = float(v)
    return out


def _lookup(a: str, b: str, dm: dict[tuple[str, str], float]) -> float:
    """查找两点间距离，无匹配时返回极大值。"""
    val = dm.get((str(a), str(b)))
    if val is not None:
        return val
    # 模糊匹配
    for (ka, kb), v in dm.items():
        if str(a) in str(ka) and str(b) in str(kb):
            return v
    return float("inf")
