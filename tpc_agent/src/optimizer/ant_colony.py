"""蚁群算法（ACO）。"""


def ant_colony_optimize(
    poi_ids: list[str],
    distance_matrix: dict,
    n_ants: int = 20,
    n_iterations: int = 100,
) -> list[str]:
    """ACO 求解 TSP 路线。

    Args:
        poi_ids: POI ID 列表。
        distance_matrix: 距离矩阵。
        n_ants: 蚂蚁数量。
        n_iterations: 迭代次数。

    Returns:
        list[str]: 最优路线。
    """
    raise NotImplementedError
