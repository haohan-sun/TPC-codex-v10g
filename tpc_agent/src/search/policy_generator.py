"""规划策略生成。"""

from src.data_layer.schema import Constraints


def generate_policies(constraints: Constraints) -> list[str]:
    """根据约束特征动态生成策略列表。

    Args:
        constraints: 约束集合。

    Returns:
        list[str]: 策略名称列表。
    """
    raise NotImplementedError
