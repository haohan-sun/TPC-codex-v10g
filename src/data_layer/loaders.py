"""数据加载层：读取比赛 query 文件。"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from src.data_layer.schema import Query


def _extract_raw_text(data: dict[str, Any]) -> str:
    """从多种字段名中提取自然语言描述。"""
    for key in ("nature_language", "nature_language_en", "raw_text", "text", "query"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_query_id(data: dict[str, Any], fallback: str) -> str:
    """从多种字段名中提取 query 唯一 ID。"""
    for key in ("uid", "query_id", "id"):
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return fallback


def query_from_dict(data: dict[str, Any], source: str = "") -> Query:
    """将原始 dict 转为标准 Query 对象（兼容 ChinaTravel 官方格式）。

    ChinaTravel 典型字段：
        uid, nature_language, start_city, target_city, days,
        people_number, hard_logic_py, tag 等。

    Args:
        data: 原始 JSON 字典。
        source: 来源文件路径（写入 metadata，便于调试）。

    Returns:
        Query: 标准化查询，raw_text 供约束解析使用，
               结构化字段保存在 metadata 中供后续模块读取。
    """
    query_id = _extract_query_id(data, fallback="unknown")
    raw_text = _extract_raw_text(data)

    # 结构化字段统一放入 metadata，constraint_parser 直接读取
    metadata: dict[str, Any] = dict(data)
    if source:
        metadata["_source_file"] = source

    return Query(query_id=query_id, raw_text=raw_text, metadata=metadata)


def load_query(source: str | Path) -> Query:
    """从 JSON 或 CSV 文件加载单条用户 query。

    支持格式：
        1. ChinaTravel JSON（单条 query 一个文件）
        2. 通用 JSON：{"query_id": "...", "raw_text": "..."}
        3. CSV：需含 query_id/raw_text 或 uid/nature_language 列

    Args:
        source: 文件路径。

    Returns:
        Query: 标准化查询对象。

    Raises:
        FileNotFoundError: 文件不存在。
        ValueError: 格式不支持或缺少必要字段。
    """
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"query 文件不存在: {path}")

    suffix = path.suffix.lower()
    if suffix == ".json":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"JSON 顶层必须是对象: {path}")
        query = query_from_dict(data, source=str(path))
    elif suffix == ".csv":
        query = _load_query_from_csv(path)
    else:
        raise ValueError(f"不支持的 query 文件格式: {suffix}，请使用 .json 或 .csv")

    if not query.raw_text and not query.metadata:
        raise ValueError(f"query 缺少有效内容: {path}")

    return query


def _load_query_from_csv(path: Path) -> Query:
    """从 CSV 读取首条有效 query。"""
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row:
                continue
            return query_from_dict(dict(row), source=str(path))
    raise ValueError(f"CSV 文件为空或无有效行: {path}")


def load_queries_batch(source_dir: str | Path, pattern: str = "*.json") -> list[Query]:
    """批量加载目录下所有 query 文件。

    Args:
        source_dir: 目录路径，例如 data/training data/。
        pattern: 文件名 glob 模式，默认 *.json。

    Returns:
        list[Query]: 按文件名排序的 query 列表。
    """
    directory = Path(source_dir)
    if not directory.exists():
        raise FileNotFoundError(f"query 目录不存在: {directory}")

    queries: list[Query] = []
    for file_path in sorted(directory.glob(pattern)):
        if file_path.is_file():
            queries.append(load_query(file_path))
    return queries
