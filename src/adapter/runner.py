"""官方 Agent 运行逻辑。"""

from __future__ import annotations

from typing import Any

from src.adapter.plan_formatter import build_empty_plan, format_official_plan, is_plan_success
from src.adapter.query_adapter import prepare_official_query
from src.data_layer.loaders import query_from_dict


def run_pipeline(query: dict[str, Any], oracle_translation: bool = False) -> dict[str, Any]:
    """调用内部 solve_one_query 主流程。

    Args:
        query: 官方 query dict。
        oracle_translation: 是否允许使用 hard_logic_py。

    Returns:
        dict: solve_one_query 返回值；失败时抛出异常由上层捕获。
    """
    internal_query = prepare_official_query(
        query,
        prob_idx=query.get("uid"),
        oracle_translation=oracle_translation,
    )

    # 延迟导入，避免循环依赖
    from main import solve_one_query

    return solve_one_query(internal_query)


def run_single_official_query(
    query: dict[str, Any],
    prob_idx: str,
    oracle_translation: bool = False,
    elapsed_sec: float = 0.0,
) -> tuple[bool, dict[str, Any]]:
    """执行单条官方 query，返回 (succ, plan_dict)。

    与 ChinaTravel TPCAgent.run() 签名一致：
        succ: 是否生成有效行程
        plan: 符合 output_schema 的 JSON dict

    Args:
        query: 官方 query dict。
        prob_idx: 样本 uid。
        oracle_translation: 是否启用 oracle DSL。
        elapsed_sec: 已消耗时间（秒），写入 plan。

    Returns:
        tuple[bool, dict]: (成功与否, 官方 plan)。
    """
    try:
        result = run_pipeline(query, oracle_translation=oracle_translation)
        plan = format_official_plan(query, result, elapsed_sec=elapsed_sec)
        return is_plan_success(plan), plan
    except NotImplementedError as exc:
        plan = build_empty_plan(
            query,
            elapsed_sec=elapsed_sec,
            error=f"pipeline_not_ready: {exc}",
        )
        return False, plan
    except Exception as exc:
        plan = build_empty_plan(
            query,
            elapsed_sec=elapsed_sec,
            error=f"{type(exc).__name__}: {exc}",
        )
        return False, plan
