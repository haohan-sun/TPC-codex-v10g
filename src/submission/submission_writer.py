"""提交格式生成。"""

from __future__ import annotations

import json
from pathlib import Path

from src.data_layer.schema import OfficialPlan, Plan
from src.planner.plan_builder import build_full_plan_dict


def render_to_official_format(plan: Plan) -> OfficialPlan:
    """将内部 Plan 转为官方提交 JSON。

    优先使用 plan.metadata['official_plan']；
    否则按 constraints/candidates 重建。

    Args:
        plan: 内部多日计划。

    Returns:
        OfficialPlan: itinerary 字段为完整官方 plan dict。
    """
    official = plan.metadata.get("official_plan")
    if not official or not official.get("itinerary"):
        official = {
            "people_number": 1,
            "start_city": "",
            "target_city": "",
            "itinerary": [],
        }
    else:
        official = {
            k: v for k, v in official.items()
            if not str(k).startswith("_")
        }

    return OfficialPlan(
        query_id=plan.query_id,
        itinerary=official,
        version="1.0",
    )


def write_submission(plan: OfficialPlan, output_path: str) -> None:
    """写入 eval_tpc.py 可读的结果 JSON 文件。"""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(plan.itinerary)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
