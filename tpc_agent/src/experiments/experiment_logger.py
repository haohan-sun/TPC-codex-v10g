"""实验记录。"""

from __future__ import annotations

import json
from pathlib import Path

from src.data_layer.paths import get_project_root, load_project_config


def save_logs(
    query,
    constraints,
    best_plan,
    best_score: float,
    all_results=None,
) -> None:
    """写入简单实验日志 JSON。"""
    config = load_project_config()
    log_dir = Path(config.get("logging", {}).get("experiment_dir", "data/outputs/experiments"))
    if not log_dir.is_absolute():
        log_dir = get_project_root() / log_dir
    log_dir.mkdir(parents=True, exist_ok=True)

    record = {
        "query_id": query.query_id,
        "score": best_score,
        "policy_results": [
            {"policy": p, "score": s} for _, s, p in (all_results or [])
        ],
    }
    path = log_dir / f"{query.query_id}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
