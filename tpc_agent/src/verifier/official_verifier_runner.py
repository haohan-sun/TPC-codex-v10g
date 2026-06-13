"""官方 verifier / eval_tpc 对接。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from src.data_layer.paths import get_project_root, load_project_config
from src.data_layer.schema import OfficialPlan, VerifierError, ErrorType
from src.verifier.eval_bridge import evaluate_plan_local, is_chinatravel_available


def run_official_verifier(plan: OfficialPlan) -> tuple[float, list[VerifierError]]:
    """调用官方评测逻辑或本地 schema 检查。

    Returns:
        tuple[float, list[VerifierError]]: (综合分 0~100, 错误列表)
    """
    plan_dict = plan.itinerary
    if not plan_dict.get("itinerary"):
        return 0.0, [VerifierError(
            error_code="EMPTY_ITINERARY",
            message="itinerary 为空",
            error_type=ErrorType.FORMAT,
        )]

    result = evaluate_plan_local(plan_dict, query_id=plan.query_id)
    errors = []
    for e in result.get("errors", []):
        try:
            et = ErrorType(e.get("type", "unknown"))
        except ValueError:
            et = ErrorType.UNKNOWN
        errors.append(VerifierError(
            error_code=e.get("code", "UNKNOWN"),
            message=e.get("message", ""),
            error_type=et,
        ))
    return float(result.get("score", 0.0)), errors
