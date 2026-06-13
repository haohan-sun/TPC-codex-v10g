"""eval_tpc.py 桥接：在 ChinaTravel 可用时调用官方评测。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from src.data_layer.paths import get_project_root, load_project_config
from src.data_layer.chinatravel_bridge import resolve_chinatravel_root as _resolve_chinatravel_root


def is_chinatravel_available() -> bool:
    return _resolve_chinatravel_root() is not None


def _validate_schema(plan: dict) -> list[dict]:
    """简易 schema 校验。"""
    errors = []
    for field in ("people_number", "start_city", "target_city", "itinerary"):
        if field not in plan:
            errors.append({"code": "SCHEMA", "message": f"缺少字段 {field}", "type": "format"})
    if not isinstance(plan.get("itinerary"), list) or len(plan.get("itinerary", [])) == 0:
        errors.append({"code": "EMPTY", "message": "itinerary 为空", "type": "format"})
    else:
        for day in plan["itinerary"]:
            for act in day.get("activities", []):
                for req in ("type", "start_time", "end_time", "cost", "price", "transports"):
                    if req not in act:
                        errors.append({"code": "ACT_SCHEMA", "message": f"activity 缺少 {req}", "type": "format"})
    return errors


def evaluate_plan_local(plan_dict: dict, query_id: str = "") -> dict[str, Any]:
    """对单条 plan 做本地评分（schema + 可选官方 commonsense）。"""
    errors = _validate_schema(plan_dict)
    score = 0.0
    if not errors:
        score = 10.0  # 基础分：非空且 schema 通过

    # 尝试官方 commonsense（需 ChinaTravel + environment 数据）
    root = _resolve_chinatravel_root()
    if root and not errors:
        try:
            root_str = str(root)
            if root_str not in sys.path:
                sys.path.insert(0, root_str)
            from chinatravel.evaluation.commonsense_constraint import evaluate_commonsense_constraints

            query = _load_query_by_id(query_id, root)
            if query:
                macro, micro, _, _ = evaluate_commonsense_constraints(
                    [query_id], {query_id: query}, {query_id: plan_dict}, verbose=False
                )
                score = 0.1 * micro + 0.1 * macro + 0.4 * (100 if micro > 99 else 0)
        except Exception as exc:
            errors.append({"code": "EVAL", "message": str(exc), "type": "unknown"})

    return {"score": score, "errors": errors}


def _load_query_by_id(query_id: str, ct_root: Path) -> dict | None:
    training = get_project_root() / "data" / "training data" / f"{query_id}.json"
    if training.exists():
        return json.loads(training.read_text(encoding="utf-8"))
    data_dir = ct_root / "chinatravel" / "data"
    if data_dir.exists():
        for sub in data_dir.iterdir():
            p = sub / f"{query_id}.json"
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
    return None


def run_eval_tpc_batch(
    splits: str,
    method: str,
    results_dir: Path | None = None,
) -> dict[str, Any]:
    """批量运行 eval_tpc（subprocess 调用官方脚本）。"""
    root = _resolve_chinatravel_root()
    if root is None:
        return {"error": "ChinaTravel 未找到，请配置 paths.chinatravel_root"}

    import subprocess
    if results_dir is None:
        results_dir = get_project_root() / "data" / "outputs" / "results" / method

    cmd = [
        sys.executable,
        str(root / "eval_tpc.py"),
        "--splits", splits,
        "--method", method,
    ]
    proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True)
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
