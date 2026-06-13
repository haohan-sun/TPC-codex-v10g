"""候选计划择优。"""

from src.data_layer.schema import OfficialPlan


def select_best_plan(
    candidates: list[tuple[OfficialPlan, float, str]],
) -> tuple[OfficialPlan, float]:
    """从多候选中选最高分。

    Args:
        candidates: (plan, score, policy) 列表。

    Returns:
        tuple[OfficialPlan, float]: (最优行程, 分数)。
    """
    raise NotImplementedError
