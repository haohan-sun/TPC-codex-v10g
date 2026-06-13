"""主动约束获取（Active SLAM 迁移）。

先判风险、再查关键数据，避免盲目加载全量 POI。
"""

from __future__ import annotations

from typing import Any

from src.active.uncertainty_analyzer import analyze_uncertainty
from src.data_layer.database import TravelDatabase, get_database
from src.data_layer.schema import ActiveInfo, ConstraintCard, Constraints, RiskProfile

# 缓存最近一次主动查询结果，供 build_candidates 在无显式传参时复用（对接 main.py）
_last_active_info: ActiveInfo | None = None


def get_last_active_info() -> ActiveInfo | None:
    """获取最近一次 active_query_selector 的结果。"""
    return _last_active_info

# 风险类别 → 需要执行的数据查询类型
RISK_TO_QUERY_TYPES: dict[str, list[str]] = {
    "spatial": ["pois", "anchor_poi", "hotels"],
    "budget": ["price_stats", "hotels", "restaurants"],
    "accommodation": ["hotels", "anchor_poi"],
    "transport": ["transports", "pois"],
    "attraction": ["pois", "must_visit"],
    "dietary": ["restaurants"],
    "logic": ["pois", "hotels", "restaurants"],
    "preference": ["pois"],
    "ticket": ["transports"],
}


def active_query_selector(
    constraints: Constraints,
    risk_profile: RiskProfile,
) -> ActiveInfo:
    """按风险优先级主动查询关键数据。

    流程：
        1. 根据 high_risk_categories 生成 priority_queries；
        2. 调用 TravelDatabase 拉取对应数据；
        3. 将结果写入 fetched_data 供 semantic / candidates 使用。

    Args:
        constraints: 约束集合。
        risk_profile: 风险画像。

    Returns:
        ActiveInfo: 优先查询列表 + 已拉取的数据。
    """
    db = get_database()
    gp = constraints.global_params
    target_city = gp.get("target_city") or ""
    start_city = gp.get("start_city") or ""

    priority_queries = _build_priority_queries(constraints, risk_profile)
    fetched_data: dict[str, Any] = {
        "target_city": target_city,
        "start_city": start_city,
        "risk_scores": dict(risk_profile.risk_scores),
        "uncertainty": analyze_uncertainty(constraints),
    }

    if not target_city:
        return ActiveInfo(
            query_id=constraints.query_id,
            priority_queries=priority_queries,
            fetched_data=fetched_data,
        )

    # --- 按优先级查询数据 ---
    query_types = _collect_query_types(risk_profile)

    if "pois" in query_types or not query_types:
        pois = db.search_pois(target_city, filters={"category": "attraction"})
        fetched_data["pois"] = pois
        fetched_data["poi_count"] = len(pois)

    if "hotels" in query_types or "budget" in risk_profile.risk_scores:
        hotels = db.search_pois(target_city, filters={"category": "hotel"})
        fetched_data["hotels"] = hotels
        fetched_data["hotel_count"] = len(hotels)

    if "restaurants" in query_types:
        restaurants = db.search_pois(target_city, filters={"category": "restaurant"})
        fetched_data["restaurants"] = restaurants
        fetched_data["restaurant_count"] = len(restaurants)

    # 空间锚点 POI（如 East Lake Park）
    anchor_info = _fetch_anchor_pois(constraints, db, target_city)
    if anchor_info:
        fetched_data["anchor_pois"] = anchor_info

    # 必去景点名称 → 尝试在数据库中匹配
    must_visit = _extract_must_visit(constraints.cards)
    if must_visit:
        fetched_data["must_visit_resolved"] = _resolve_must_visit(
            must_visit, fetched_data.get("pois", []), db, target_city
        )

    # 价格统计（辅助预算规划）
    if "price_stats" in query_types or _has_budget_constraint(constraints.cards):
        fetched_data["price_stats"] = _compute_price_stats(fetched_data)

    # 交通选项（城际 + 市内默认）
    if "transports" in query_types:
        fetched_data["transports"] = _build_transport_options(
            start_city, target_city, gp.get("people_number")
        )

    result = ActiveInfo(
        query_id=constraints.query_id,
        priority_queries=priority_queries,
        fetched_data=fetched_data,
    )

    # 写入缓存，供 candidates 模块在 main.py 未显式传 active_info 时使用
    global _last_active_info
    _last_active_info = result
    return result


def _build_priority_queries(
    constraints: Constraints,
    risk_profile: RiskProfile,
) -> list[str]:
    """生成人类可读的优先查询描述列表。"""
    queries: list[str] = []
    gp = constraints.global_params
    target = gp.get("target_city", "?")
    start = gp.get("start_city", "?")

    for category in risk_profile.high_risk_categories:
        score = risk_profile.risk_scores.get(category, 0)
        queries.append(f"[风险={score:.2f}] 优先补全 {category} 约束数据 @ {target}")

    # 针对具体约束卡片生成更细粒度查询
    for card in constraints.cards:
        if card.category == "budget":
            btype = card.parameters.get("budget_type", "total")
            amount = card.parameters.get("max_cost")
            queries.append(f"查询 {target} 的 {btype} 价格分布，预算上限={amount}")
        elif card.category == "spatial" and card.parameters.get("anchor_poi"):
            anchor = card.parameters["anchor_poi"]
            dist = card.parameters.get("max_distance_km")
            queries.append(f"查询 {target} 距 {anchor} <= {dist}km 的酒店")
        elif card.category == "accommodation" and card.parameters.get("required_type"):
            queries.append(
                f"查询 {target} 含 '{card.parameters['required_type']}' 特征的酒店"
            )
        elif card.category == "transport" and card.parameters.get("intercity_mode"):
            mode = card.parameters["intercity_mode"]
            queries.append(f"查询 {start} -> {target} 的 {mode} 城际选项")

    # 去重保序
    seen: set[str] = set()
    unique: list[str] = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            unique.append(q)
    return unique


def _collect_query_types(risk_profile: RiskProfile) -> set[str]:
    """从高风险类别汇总需要的数据查询类型。"""
    types: set[str] = set()
    categories = risk_profile.high_risk_categories or list(risk_profile.risk_scores.keys())
    for cat in categories:
        types.update(RISK_TO_QUERY_TYPES.get(cat, []))
    return types


def _fetch_anchor_pois(
    constraints: Constraints,
    db: TravelDatabase,
    city: str,
) -> list[dict[str, Any]]:
    """查找空间约束中的锚点 POI 详情。"""
    anchors: list[dict[str, Any]] = []
    for card in constraints.cards:
        if card.category != "spatial":
            continue
        anchor_name = card.parameters.get("anchor_poi")
        if not anchor_name:
            continue
        # 先在已有 POI 中按名称搜索
        matched = db.search_pois(
            city,
            filters={"category": "attraction", "name_contains": anchor_name},
        )
        if matched:
            anchors.append({**matched[0], "constraint_card_id": card.card_id})
        else:
            anchors.append({
                "name": anchor_name,
                "resolved": False,
                "constraint_card_id": card.card_id,
            })
    return anchors


def _extract_must_visit(cards: list[ConstraintCard]) -> list[str]:
    """提取必去景点名称列表。"""
    names: list[str] = []
    for card in cards:
        if card.category == "attraction" and card.parameters.get("must_visit_poi"):
            names.append(card.parameters["must_visit_poi"])
    return names


def _resolve_must_visit(
    names: list[str],
    pois: list[dict],
    db: TravelDatabase,
    city: str,
) -> list[dict[str, Any]]:
    """将必去景点名称匹配到 POI 记录。"""
    resolved: list[dict[str, Any]] = []
    for name in names:
        found = None
        for poi in pois:
            if name.lower() in str(poi.get("name", "")).lower():
                found = poi
                break
        if not found:
            search = db.search_pois(
                city,
                filters={"category": "attraction", "name_contains": name},
            )
            found = search[0] if search else None
        resolved.append({"query_name": name, "poi": found, "matched": found is not None})
    return resolved


def _has_budget_constraint(cards: list[ConstraintCard]) -> bool:
    """是否存在预算类约束。"""
    return any(c.category == "budget" for c in cards)


def _compute_price_stats(fetched_data: dict[str, Any]) -> dict[str, Any]:
    """基于已拉取 POI 计算价格统计。"""
    stats: dict[str, Any] = {}

    for key, label in (("hotels", "accommodation"), ("restaurants", "dining"), ("pois", "attraction")):
        records = fetched_data.get(key) or []
        prices = []
        for rec in records:
            price = rec.get("price") or rec.get("cost") or rec.get("avg_price")
            if price is not None:
                try:
                    prices.append(float(price))
                except (TypeError, ValueError):
                    pass
        if prices:
            stats[label] = {
                "min": min(prices),
                "max": max(prices),
                "avg": sum(prices) / len(prices),
                "count": len(prices),
            }
        else:
            stats[label] = {"min": 0, "max": 0, "avg": 0, "count": 0}

    return stats


def _build_transport_options(
    start_city: str,
    target_city: str,
    people_number: int | None,
) -> list[dict[str, Any]]:
    """构建默认交通选项（无官方交通库时的占位结构）。"""
    people = people_number or 1
    options = [
        {
            "mode": "airplane",
            "from": start_city,
            "to": target_city,
            "people": people,
            "estimated_cost_per_person": 800,
        },
        {
            "mode": "train",
            "from": start_city,
            "to": target_city,
            "people": people,
            "estimated_cost_per_person": 400,
        },
        {
            "mode": "metro",
            "scope": "innercity",
            "estimated_cost_per_person": 5,
        },
        {
            "mode": "taxi",
            "scope": "innercity",
            "estimated_cost_per_taxi": 30,
            "people_per_taxi": 4,
        },
    ]
    return options
