"""官方 query 格式适配。"""

from __future__ import annotations

import copy
from typing import Any

from src.data_layer.loaders import query_from_dict
from src.data_layer.schema import Query


# 比赛正式推理时禁止使用的 oracle 字段
ORACLE_FIELDS = ("hard_logic_py", "hard_logic_nl", "hard_logic")


def prepare_official_query(
    query: dict[str, Any],
    prob_idx: str | None = None,
    oracle_translation: bool = False,
) -> Query:
    """将 ChinaTravel 官方 query dict 转为内部 Query 对象。

    Args:
        query: 官方 query 字典（含 uid/nature_language 等）。
        prob_idx: run_tpc 传入的样本 ID，用于补全 uid。
        oracle_translation: True=保留 hard_logic_py（仅本地 debug）；
                            False=剥离 oracle 字段（比赛正式模式）。

    Returns:
        Query: 内部标准 Query。
    """
    data = copy.deepcopy(query)

    if prob_idx and not data.get("uid"):
        data["uid"] = prob_idx

    if not oracle_translation:
        for field in ORACLE_FIELDS:
            data.pop(field, None)

    return query_from_dict(data, source=prob_idx or data.get("uid", ""))


def extract_plan_meta(query: dict[str, Any]) -> dict[str, Any]:
    """从 query 中提取写入官方 plan 顶层的元信息。"""
    return {
        "people_number": int(query.get("people_number", 1)),
        "start_city": str(query.get("start_city", "")),
        "target_city": str(query.get("target_city", "")),
    }
