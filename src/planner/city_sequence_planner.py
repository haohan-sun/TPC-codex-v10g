"""跨城市行程顺序规划。"""

from src.data_layer.schema import Constraints


def plan_city_sequence(constraints: Constraints) -> list[str]:
    """规划多城市访问顺序。

    Args:
        constraints: 约束集合。

    Returns:
        list[str]: 城市访问顺序。
    """
    raise NotImplementedError
