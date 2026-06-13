"""路线评分。"""


def score_route(route: list[str], distance_matrix: dict) -> float:
    """计算路线总成本/时间。

    Args:
        route: POI 访问顺序。
        distance_matrix: 距离矩阵。

    Returns:
        float: 路线分数（越低越好）。
    """
    raise NotImplementedError
