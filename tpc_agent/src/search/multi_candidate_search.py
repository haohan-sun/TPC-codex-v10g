"""多候选搜索。"""

from typing import Callable

from src.data_layer.schema import CandidatePool, Constraints, OfficialPlan, Query


def multi_candidate_search(
    query: Query,
    constraints: Constraints,
    candidates: CandidatePool,
    plan_builder: Callable[..., OfficialPlan],
    policies: list[str],
) -> tuple[OfficialPlan, float]:
    """同一 query 多策略生成，verifier 择优。

    输入: query + policies
    输出: best plan

    Args:
        query: 用户查询。
        constraints: 约束集合。
        candidates: 候选池。
        plan_builder: 单策略计划构建函数。
        policies: 策略列表。

    Returns:
        tuple[OfficialPlan, float]: (最优行程, 最高分)。
    """
    raise NotImplementedError
