"""官方 plan JSON 格式化。"""

from __future__ import annotations

from typing import Any


def build_empty_plan(query: dict[str, Any], elapsed_sec: float = 0.0, error: str = "") -> dict[str, Any]:
    """构建符合 ChinaTravel output_schema 的空 plan（规划失败时使用）。

    官方 TPCAgent 空实现返回 itinerary=[]，eval_tpc 仍可读取文件。
    """
    plan: dict[str, Any] = {
        "people_number": int(query.get("people_number", 1)),
        "start_city": str(query.get("start_city", "")),
        "target_city": str(query.get("target_city", "")),
        "itinerary": [],
        "elapsed_time(sec)": round(elapsed_sec, 3),
    }
    if error:
        plan["error"] = error
    return plan


def format_official_plan(
    query: dict[str, Any],
    pipeline_result: dict[str, Any] | None,
    elapsed_sec: float,
) -> dict[str, Any]:
    """将 solve_one_query 返回值转为官方提交 plan 字典。

    官方 schema 顶层字段：
        people_number, start_city, target_city, itinerary

    Args:
        query: 原始官方 query。
        pipeline_result: solve_one_query 返回 dict；None 表示失败。
        elapsed_sec: 耗时秒数。

    Returns:
        dict: 可直接被 eval_tpc.py 读取的 plan JSON。
    """
    if not pipeline_result:
        return build_empty_plan(query, elapsed_sec=elapsed_sec)

    itinerary_payload = pipeline_result.get("itinerary")

    # 情况 1：pipeline 已返回完整官方结构
    if isinstance(itinerary_payload, dict) and "itinerary" in itinerary_payload:
        plan = dict(itinerary_payload)
        plan.setdefault("people_number", int(query.get("people_number", 1)))
        plan.setdefault("start_city", str(query.get("start_city", "")))
        plan.setdefault("target_city", str(query.get("target_city", "")))
    # 情况 2：pipeline 只返回 day 列表
    elif isinstance(itinerary_payload, list):
        plan = {
            "people_number": int(query.get("people_number", 1)),
            "start_city": str(query.get("start_city", "")),
            "target_city": str(query.get("target_city", "")),
            "itinerary": itinerary_payload,
        }
    else:
        plan = build_empty_plan(query, elapsed_sec=elapsed_sec, error="invalid pipeline itinerary")

    plan["elapsed_time(sec)"] = round(elapsed_sec, 3)

    # 附加内部调试字段（不影响 schema 必需项校验）
    if pipeline_result.get("score") is not None:
        plan["_internal_score"] = pipeline_result["score"]
    if pipeline_result.get("query_id"):
        plan["_internal_query_id"] = pipeline_result["query_id"]

    return plan


def is_plan_success(plan: dict[str, Any]) -> bool:
    """判断 plan 是否包含有效行程（非空 itinerary 且无 error）。"""
    if plan.get("error"):
        return False
    itinerary = plan.get("itinerary")
    return isinstance(itinerary, list) and len(itinerary) > 0
