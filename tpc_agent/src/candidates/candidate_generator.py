"""候选池构建：压缩搜索空间，输出 Top-K POI/酒店/餐厅/交通。"""

from __future__ import annotations

from typing import Any

from src.candidates.hotel_ranker import rank_hotels
from src.candidates.poi_ranker import rank_pois
from src.candidates.restaurant_ranker import rank_restaurants
from src.candidates.transport_ranker import rank_transports
from src.data_layer.database import get_database
from src.data_layer.paths import get_project_root, load_project_config
from src.data_layer.schema import (
    ActiveInfo,
    CandidatePool,
    Constraints,
    GroundedPreferences,
)


def _load_candidate_config() -> dict[str, int]:
    """从 config.yaml 读取候选池 Top-K 配置。"""
    defaults = {"top_k_pois": 50, "top_k_restaurants": 30, "top_k_hotels": 10}
    config = load_project_config()
    section = config.get("candidates") or {}

    # 简易 fallback：若 config 解析不完整，尝试直接读 yaml 文本
    if not section:
        config_path = get_project_root() / "config.yaml"
        if config_path.exists():
            text = config_path.read_text(encoding="utf-8")
            for key in defaults:
                for line in text.splitlines():
                    if line.strip().startswith(f"{key}:"):
                        try:
                            defaults[key] = int(line.split(":", 1)[1].strip())
                        except ValueError:
                            pass
                        break
        return defaults

    return {
        "top_k_pois": int(section.get("top_k_pois", defaults["top_k_pois"])),
        "top_k_restaurants": int(section.get("top_k_restaurants", defaults["top_k_restaurants"])),
        "top_k_hotels": int(section.get("top_k_hotels", defaults["top_k_hotels"])),
    }


def build_candidates(
    constraints: Constraints,
    preferences: GroundedPreferences,
    active_info: ActiveInfo | None = None,
) -> CandidatePool:
    """压缩搜索空间，构建 POI / 酒店 / 餐厅 / 交通候选池。

    流程：
        1. 优先使用 active_info 中已拉取的数据；
        2. 不足时回退到 TravelDatabase 直接查询；
        3. 按约束过滤 + 偏好排序 + Top-K 截断。

    Args:
        constraints: 约束集合。
        preferences: 语义落地偏好权重。
        active_info: 主动查询结果（main.py 上游产出，可选）。

    Returns:
        CandidatePool: 压缩后的候选池。
    """
    cfg = _load_candidate_config()
    gp = constraints.global_params
    target_city = gp.get("target_city") or ""
    db = get_database()

    # main.py 当前只传 constraints/preferences，此处自动复用 active 阶段缓存
    if active_info is None:
        from src.active.active_query_selector import get_last_active_info
        active_info = get_last_active_info()

    fetched: dict[str, Any] = (active_info.fetched_data if active_info else {}) or {}

    # --- 1. 获取原始 POI 列表 ---
    raw_pois = fetched.get("pois") or _load_from_db(db, target_city, "attraction")
    raw_hotels = fetched.get("hotels") or _load_from_db(db, target_city, "hotel")
    raw_restaurants = fetched.get("restaurants") or _load_from_db(db, target_city, "restaurant")
    raw_transports = fetched.get("transports") or []

    # --- 2. 提取必去 POI ID ---
    must_visit_ids = _collect_must_visit_ids(constraints, fetched)

    # --- 3. 排序截断 ---
    poi_candidates = rank_pois(
        raw_pois,
        preferences,
        top_k=cfg["top_k_pois"],
        must_visit_ids=must_visit_ids,
    )
    hotel_candidates = rank_hotels(
        raw_hotels,
        constraints,
        top_k=cfg["top_k_hotels"],
        anchor_pois=fetched.get("anchor_pois"),
    )
    restaurant_candidates = rank_restaurants(
        raw_restaurants,
        preferences,
        constraints=constraints,
        top_k=cfg["top_k_restaurants"],
    )
    transport_options = rank_transports(raw_transports, constraints)

    return CandidatePool(
        query_id=constraints.query_id,
        pois=poi_candidates,
        hotels=hotel_candidates,
        restaurants=restaurant_candidates,
        transports=transport_options,
    )


def _load_from_db(db, city: str, category: str) -> list[dict[str, Any]]:
    """从数据库加载指定城市 POI（city 为空时返回空列表）。"""
    if not city:
        return []
    return db.search_pois(city, filters={"category": category})


def _collect_must_visit_ids(
    constraints: Constraints,
    fetched: dict[str, Any],
) -> set[str]:
    """汇总必去景点 ID（来自约束卡片 + active_info 解析结果）。"""
    ids: set[str] = set()

    # 从 active_info 已解析的必去项
    for item in fetched.get("must_visit_resolved") or []:
        poi = item.get("poi")
        if poi and item.get("matched"):
            for key in ("id", "poi_id", "uid", "name"):
                if poi.get(key):
                    ids.add(str(poi[key]))
                    break

    # 从约束卡片中的名称做模糊匹配（若 active_info 未解析）
    resolved_names = {
        str(item.get("query_name", "")).lower()
        for item in (fetched.get("must_visit_resolved") or [])
    }
    for card in constraints.cards:
        if card.category != "attraction":
            continue
        name = card.parameters.get("must_visit_poi")
        if not name or name.lower() in resolved_names:
            continue
        ids.add(str(name))  # 用名称作为 ID 占位，rank_pois 中按名称匹配

    return ids
