"""技能：按区域聚类 POI — 同日景点尽量在同一区域，减少跨区交通。"""

from typing import Any


def group_pois_by_region(plan, **kwargs) -> dict:
    """根据经纬度将 POI 分为 2-3 个地理簇。

    同一簇的 POI 应安排在同一天。
    """
    candidates = kwargs.get("candidates")
    if candidates is None:
        return plan

    pois = candidates.pois or []
    coords: list[tuple[str, float, float]] = []
    for p in pois:
        meta = p.metadata or {}
        lat = meta.get("lat") or meta.get("latitude")
        lon = meta.get("lng") or meta.get("lon") or meta.get("longitude")
        if lat is not None and lon is not None:
            coords.append((p.name, float(lat), float(lon)))

    if len(coords) < 4:
        # 太少不需要聚类
        plan.metadata["poi_regions"] = {}
        return plan

    # 简易 K-means (k=min(3, len(coords)//2))
    import math
    k = min(3, max(2, len(coords) // 2))
    # 用最远点初始化
    centers = [coords[0][1:]]
    for _ in range(k - 1):
        best = max(coords, key=lambda c: min(
            math.sqrt((c[1] - cx) ** 2 + (c[2] - cy) ** 2)
            for cx, cy in centers
        ))
        centers.append(best[1:])

    # 分配
    regions: dict[int, list[str]] = {i: [] for i in range(k)}
    for name, lat, lon in coords:
        ci = min(range(k), key=lambda i: math.sqrt((lat - centers[i][0]) ** 2 + (lon - centers[i][1]) ** 2))
        regions[ci].append(name)

    plan.metadata["poi_regions"] = regions
    return plan
