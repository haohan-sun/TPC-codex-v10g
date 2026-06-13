"""最近邻启发式。"""

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
        start_id: 起点 ID。

    Returns:
        list[str]: 排序后 POI ID。
    """
    raise NotImplementedError
