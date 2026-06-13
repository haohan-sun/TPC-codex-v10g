"""消融实验。"""

from typing import Callable


def run_ablation(
    module_name: str,
    baseline_fn: Callable,
    ablated_fn: Callable,
    test_queries: list,
) -> dict[str, float]:
    """对指定模块做消融对比。

    Args:
        module_name: 模块名称。
        baseline_fn: 完整系统函数。
        ablated_fn: 去掉该模块的函数。
        test_queries: 测试 query 列表。

    Returns:
        dict[str, float]: 指标对比结果。
    """
    raise NotImplementedError
