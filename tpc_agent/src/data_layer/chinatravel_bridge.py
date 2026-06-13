"""ChinaTravel 环境路径解析与 CSV 数据桥接。"""

from __future__ import annotations

import csv
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.data_layer.paths import get_project_root, load_project_config

CITY_SLUGS = [
    "beijing", "shanghai", "nanjing", "suzhou", "hangzhou",
    "shenzhen", "chengdu", "wuhan", "guangzhou", "chongqing",
]
CITY_NAMES_EN = [
    "Beijing", "Shanghai", "Nanjing", "Suzhou", "Hangzhou",
    "Shenzhen", "Chengdu", "Wuhan", "Guangzhou", "Chongqing",
]
CITY_NAMES_ZH = [
    "北京", "上海", "南京", "苏州", "杭州",
    "深圳", "成都", "武汉", "广州", "重庆",
]


def resolve_chinatravel_root() -> Path | None:
    """解析 ChinaTravel 仓库根目录。"""
    config = load_project_config()
    raw = (config.get("paths") or {}).get("chinatravel_root")
    candidates: list[Path] = []
    if raw:
        p = Path(raw)
        candidates.append(p if p.is_absolute() else get_project_root() / p)
    candidates.extend([
        get_project_root().parent / "ChinaTravel",
        get_project_root().parent / "chinatravel",
    ])
    for path in candidates:
        if (path / "chinatravel" / "environment").exists():
            return path
        if (path / "eval_tpc.py").exists():
            return path
    return None


def ensure_chinatravel_on_path() -> Path | None:
    """将 ChinaTravel 加入 sys.path。"""
    root = resolve_chinatravel_root()
    if root is None:
        return None
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    return root


def infer_lang(city: str) -> str:
    """根据城市名推断语言（training 数据多为英文名）。"""
    if any("\u4e00" <= ch <= "\u9fff" for ch in city):
        return "zh"
    return "en"


def database_dir(lang: str | None = None) -> Path | None:
    """返回 environment/database 或 database_en 目录。"""
    root = resolve_chinatravel_root()
    if root is None:
        return None
    lang = infer_lang("") if lang is None else lang
    env_root = root / "chinatravel" / "environment"
    for name in ("database_en", "database") if lang == "en" else ("database", "database_en"):
        path = env_root / name
        if path.exists() and any(path.iterdir()):
            return path
    return None


def is_chinatravel_database_ready(lang: str | None = None) -> bool:
    """environment CSV 数据库是否已下载。"""
    db = database_dir(lang)
    if db is None:
        return False
    sample = db / "attractions" / "chengdu" / "attractions.csv"
    return sample.exists()


def city_slug(city: str) -> str | None:
    """城市名 → slug（支持中英文）。"""
    city = city.strip()
    for slug, en, zh in zip(CITY_SLUGS, CITY_NAMES_EN, CITY_NAMES_ZH):
        if city.lower() == slug or city == en or city == zh:
            return slug
    return city.lower().replace(" ", "")


def load_csv_records(city: str, category: str, lang: str | None = None) -> list[dict[str, Any]]:
    """从 ChinaTravel CSV 加载 POI 记录。"""
    db = database_dir(lang or infer_lang(city))
    if db is None:
        return []
    slug = city_slug(city)
    if slug is None:
        return []

    folder_map = {
        "attraction": "attractions",
        "hotel": "accommodations",
        "accommodation": "accommodations",
        "restaurant": "restaurants",
    }
    folder = folder_map.get(category, category)
    csv_path = db / folder / slug / f"{folder.rstrip('s') if folder.endswith('s') else folder}.csv"
    # 修正路径: attractions/chengdu/attractions.csv
    if folder == "attractions":
        csv_path = db / "attractions" / slug / "attractions.csv"
    elif folder == "accommodations":
        csv_path = db / "accommodations" / slug / "accommodations.csv"
    elif folder == "restaurants":
        csv_path = db / "restaurants" / slug / "restaurants.csv"

    if not csv_path.exists():
        return []

    records: list[dict[str, Any]] = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            item = dict(row)
            item.setdefault("name", item.get("name", ""))
            item.setdefault("city", city)
            item.setdefault("category", category)
            for key in ("price", "lat", "lon", "id"):
                if key in item and item[key] not in ("", None):
                    try:
                        if key == "id":
                            item[key] = int(float(item[key]))
                        else:
                            item[key] = float(item[key])
                    except (TypeError, ValueError):
                        pass
            records.append(item)
    return records


@lru_cache(maxsize=4)
def get_world_env(lang: str = "en"):
    """获取 WorldEnv；数据库未就绪时返回 None。"""
    if not ensure_chinatravel_on_path():
        return None
    if not is_chinatravel_database_ready(lang):
        return None
    try:
        from chinatravel.environment.world_env import WorldEnv

        return WorldEnv(lang=lang)
    except Exception:
        return None
