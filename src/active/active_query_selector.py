"""主动约束获取（Active Constraint Mapping 升级版）。

先建立 belief state，再按 info_gain / query_cost 选择结构化查询，
避免盲目加载全量数据。每个查询决策可解释。

与旧版区别:
    - 不再使用硬编码 RISK_TO_QUERY_TYPES 字典
    - 引入 belief state / information gain / query cost / explanation
    - 查询动作映射到 agent_env structured tools
"""

from __future__ import annotations

from typing import Any

from src.active.active_constraint_mapping import (
    active_constraint_mapping,
    init_beliefs,
    update_beliefs,
)
from src.active.uncertainty_analyzer import analyze_uncertainty
from src.data_layer.database import TravelDatabase, get_database
from src.data_layer.schema import ActiveAction, ActiveInfo, ConstraintCard, Constraints, RiskProfile

# 缓存最近一次结果，供 build_candidates 复用
_last_active_info: ActiveInfo | None = None


def get_last_active_info() -> ActiveInfo | None:
    """获取最近一次 active_query_selector 的结果。"""
    return _last_active_info


def active_query_selector(
    constraints: Constraints,
    risk_profile: RiskProfile,
    max_actions: int = 6,
) -> ActiveInfo:
    """按 Active Constraint Mapping 主动查询关键数据。

    流程:
        1. 使用 active_constraint_mapping() 生成 belief state + 候选动作 + 选择 + 解释
        2. 调用 TravelDatabase 执行被选中的查询
        3. 将结果写入 fetched_data 供 semantic / candidates 使用
        4. 更新 belief state

    Args:
        constraints: 约束集合。
        risk_profile: 风险画像。
        max_actions: 最多执行的查询动作数。

    Returns:
        ActiveInfo: 含优先查询列表 + 已拉取数据 + 选择解释。
    """
    # ---- 1. Active Constraint Mapping 决策 ----
    mapping_result = active_constraint_mapping(
        constraints=constraints,
        risk_profile=risk_profile,
        max_actions=max_actions,
    )

    db = get_database()
    gp = constraints.global_params
    target_city = gp.get("target_city") or ""
    start_city = gp.get("start_city") or ""

    # ---- 2. 初始化 fetched_data ----
    fetched_data: dict[str, Any] = {
        "target_city": target_city,
        "start_city": start_city,
        "risk_scores": dict(risk_profile.risk_scores),
        "uncertainty": analyze_uncertainty(constraints),
        "required_attraction_types": _extract_card_values(constraints.cards, "must_visit_type"),
        "forbidden_attraction_types": _extract_card_values(constraints.cards, "forbidden_attraction_type"),
        "forbidden_pois": _extract_card_values(constraints.cards, "forbidden_poi"),
        # ACM 元数据
        "acm_beliefs": {
            cat: {"resolved": b.resolved, "confidence": b.confidence, "risk": b.risk_level}
            for cat, b in mapping_result.beliefs.items()
        },
        "acm_explanations": mapping_result.explanation_summary,
    }

    # ---- 3. 构建 priority_queries 列表（人类可读 + 结构化） ----
    priority_queries: list[str] = []
    for action in mapping_result.selected_actions:
        priority_queries.append(
            f"[{action.target_category}] {action.tool_name} "
            f"| gain={action.expected_info_gain:.3f} cost={action.query_cost:.3f} "
            f"| {action.selection_reason}"
        )

    if not target_city:
        return ActiveInfo(
            query_id=constraints.query_id,
            priority_queries=priority_queries,
            fetched_data=fetched_data,
        )

    # ---- 4. 执行数据拉取 + 保存结果到 fetched_data ----
    action_results: dict[str, dict[str, Any]] = {}
    query_results: dict[str, Any] = {}
    covered_data: set[str] = set()  # 记录哪些数据类别已被 action result 覆盖

    for action in mapping_result.selected_actions:
        raw_result = _execute_action(action, db, target_city, start_city, constraints)
        if raw_result is not None:
            is_list = isinstance(raw_result, list)
            record_count = len(raw_result) if is_list else (1 if isinstance(raw_result, dict) else 0)
            action_results[action.action_id] = {
                "tool_name": action.tool_name,
                "params": action.params,
                "target_category": action.target_category,
                "record_count": record_count,
                "data": raw_result,
            }
            # 标记已覆盖的数据类别
            covered_data.update(_covered_categories(action.tool_name))

        # 全局 tool_name 索引（供 update_beliefs）
        query_results[action.tool_name] = raw_result

    fetched_data["action_results"] = action_results

    # ---- 5. 按需填充 fetched_data ——
    # 策略：优先用 action result 中有数据的；空结果或未覆盖 → 全量扫兜底。
    _fill_category(
        fetched_data, action_results, covered_data, db, target_city,
        category_key="attractions", data_key="pois", count_key="poi_count",
        db_category="attraction", source_key="_poi_source",
    )
    _fill_category(
        fetched_data, action_results, covered_data, db, target_city,
        category_key="accommodations", data_key="hotels", count_key="hotel_count",
        db_category="hotel", source_key="_hotel_source",
    )
    _fill_category(
        fetched_data, action_results, covered_data, db, target_city,
        category_key="restaurants", data_key="restaurants", count_key="restaurant_count",
        db_category="restaurant", source_key="_restaurant_source",
    )

    # 锚点 POI
    anchor_info = _fetch_anchor_pois(constraints, db, target_city)
    if anchor_info:
        fetched_data["anchor_pois"] = anchor_info

    # 必去景点
    must_visit = _extract_must_visit(constraints.cards)
    if must_visit:
        fetched_data["must_visit_resolved"] = _resolve_must_visit(
            must_visit, fetched_data.get("pois", []), db, target_city
        )

    # 价格统计
    if _has_budget_constraint(constraints.cards):
        fetched_data["price_stats"] = _compute_price_stats(fetched_data)

    # 交通选项
    fetched_data["transports"] = _build_transport_options(
        start_city, target_city, gp.get("people_number")
    )

    # ---- 6. 更新 belief state ----
    update_beliefs(mapping_result.beliefs, mapping_result.selected_actions, query_results)

    # ---- 7. 写入结构化 actions 到 fetched_data ----
    fetched_data["selected_actions"] = [
        {
            "action_id": a.action_id,
            "tool_name": a.tool_name,
            "params": a.params,
            "target_category": a.target_category,
            "info_gain": a.expected_info_gain,
            "query_cost": a.query_cost,
            "priority_score": a.priority_score,
            "reason": a.selection_reason,
        }
        for a in mapping_result.selected_actions
    ]

    result = ActiveInfo(
        query_id=constraints.query_id,
        priority_queries=priority_queries,
        fetched_data=fetched_data,
    )

    global _last_active_info
    _last_active_info = result
    return result


# ---------------------------------------------------------------------------
# Action execution (data fetching)
# ---------------------------------------------------------------------------

def _execute_action(
    action: ActiveAction,
    db: TravelDatabase,
    target_city: str,
    start_city: str,
    constraints: Constraints,
) -> Any:
    """执行单个 ActiveAction 的数据查询。

    优先使用 agent_env backend（通过 SandboxClient），
    select 类工具会应用 action.params 中的 key/op/value 过滤条件。
    """
    tool = action.tool_name
    params = action.params
    city = params.get("city", target_city)

    try:
        from src.data_layer.world_env_client import get_sandbox, AgentEnvBackend
        from src.data_layer.chinatravel_bridge import infer_lang

        sandbox = get_sandbox(infer_lang(city))

        # -- nearby 类（直接传参） --
        if tool == "accommodations_nearby" and sandbox.has_world_env:
            return sandbox.hotels_nearby(
                city=city,
                anchor=params.get("point", ""),
                topk=params.get("topk", 10),
                max_dist_km=params.get("dist", 8.0),
            )
        elif tool == "attractions_nearby" and sandbox.has_world_env:
            return sandbox.attractions_nearby(
                city=city,
                point=params.get("point", ""),
                topk=params.get("topk", 10),
                max_dist_km=params.get("dist", 5.0),
            )
        elif tool == "restaurants_nearby" and sandbox.has_world_env:
            return sandbox.restaurants_nearby(
                city=city,
                point=params.get("point", ""),
                topk=params.get("topk", 10),
                max_dist_km=params.get("dist", 5.0),
            )

        # -- select 类（应用 key/op/value 过滤） --
        elif tool == "attractions_select":
            records = _select_with_filter(
                sandbox, "attractions", city, params, default_limit=50,
            )
            if records is not None:
                return records
        elif tool == "restaurants_select":
            records = _select_with_filter(
                sandbox, "restaurants", city, params, default_limit=30,
            )
            if records is not None:
                return records
        elif tool == "accommodations_select":
            records = _select_with_filter(
                sandbox, "accommodations", city, params, default_limit=20,
            )
            if records is not None:
                return records
        elif tool == "attractions_types":
            # 只返回类型列表（轻量）
            if sandbox.has_world_env:
                records = sandbox.list_attractions(city, limit=100)
                types = sorted(set(
                    str(r.get("type", "")) for r in records if r.get("type")
                ))
                return [{"attraction_type": t} for t in types]

        # -- 坐标查询 --
        elif tool == "poi_lat_lon_search":
            if sandbox.has_world_env:
                coords = sandbox.poi_lat_lon(city=city, name=params.get("name", ""))
                if coords:
                    return coords

        # -- 交通查询 --
        elif tool == "intercity_transport_select":
            if sandbox.has_world_env:
                return sandbox.select_intercity(
                    start_city=params.get("start_city", start_city),
                    end_city=params.get("end_city", target_city),
                    mode=params.get("intercity_type", "train"),
                    earliest=params.get("earliest_leave_time", "06:00"),
                )
        elif tool == "goto":
            if sandbox.has_world_env:
                return sandbox.goto(
                    city=city,
                    start=params.get("start", ""),
                    end=params.get("end", ""),
                    start_time=params.get("start_time", "09:00"),
                    mode=params.get("transport_type", "metro"),
                )

        # -- cuisine --
        elif tool == "restaurants_cuisine":
            records = sandbox.list_restaurants(city, limit=100) if sandbox.has_world_env else []
            if records:
                cuisines = sorted(set(
                    str(r.get("cuisine", "")) for r in records if r.get("cuisine")
                ))
                return [{"cuisine": c} for c in cuisines]

    except Exception:
        pass

    # -- Fallback: TravelDatabase (no WorldEnv / agent_env) --
    if tool in ("attractions_select", "attractions_types"):
        return _apply_client_filter(
            db.search_pois(city, filters={"category": "attraction"}), params,
        )
    elif tool == "restaurants_select":
        return _apply_client_filter(
            db.search_pois(city, filters={"category": "restaurant"}), params,
        )
    elif tool == "accommodations_select":
        return _apply_client_filter(
            db.search_pois(city, filters={"category": "hotel"}), params,
        )
    elif tool == "restaurants_cuisine":
        records = db.search_pois(city, filters={"category": "restaurant"})
        cuisines = sorted(set(str(r.get("cuisine", "")) for r in records if r.get("cuisine")))
        return [{"cuisine": c} for c in cuisines]
    elif tool == "attractions_types":
        records = db.search_pois(city, filters={"category": "attraction"})
        types = sorted(set(str(r.get("type", "")) for r in records if r.get("type")))
        return [{"attraction_type": t} for t in types]

    return None


# ---------------------------------------------------------------------------
# Param-aware select helpers
# ---------------------------------------------------------------------------

def _select_with_filter(
    sandbox,
    category: str,        # "attractions" | "restaurants" | "accommodations"
    city: str,
    params: dict[str, Any],
    default_limit: int = 50,
) -> list[dict[str, Any]] | None:
    """Use agent_env select_* with key/op/value from params, fallback to list_* + client filter."""
    key = params.get("key")
    op = params.get("op")
    value = params.get("value")

    # Try agent_env structured select first
    if sandbox._agent_env and key and op and value is not None:
        try:
            if category == "attractions":
                return sandbox._agent_env.select_attractions(city, str(key), str(op), value)
            elif category == "restaurants":
                return sandbox._agent_env.select_restaurants(city, str(key), str(op), value)
            elif category == "accommodations":
                return sandbox._agent_env.select_accommodations(city, str(key), str(op), value)
        except Exception:
            pass

    # Fallback: unfiltered list + client-side filter
    list_fn = {
        "attractions": sandbox.list_attractions,
        "restaurants": sandbox.list_restaurants,
        "accommodations": sandbox.list_hotels,
    }.get(category)

    if list_fn is None:
        return None

    try:
        records = list_fn(city, limit=default_limit * 2)
        return _apply_client_filter(records, params)
    except Exception:
        return None


def _apply_client_filter(
    records: list[dict[str, Any]],
    params: dict[str, Any],
) -> list[dict[str, Any]]:
    """Client-side filter for select-style params (key/op/value).

    Supports: eq, ne, contains, le, ge, lt, gt.
    When key is "name" and op is "ne" with value "", returns all records (no filter).
    """
    key = params.get("key")
    op = params.get("op")
    value = params.get("value")

    if not key or not op:
        return records
    # "ne" with empty value = select all
    if op == "ne" and (value is None or value == ""):
        return records

    filtered: list[dict[str, Any]] = []
    for rec in records:
        field_val = rec.get(key)
        if field_val is None:
            # try common aliases
            for alias in _FIELD_ALIASES.get(str(key), []):
                field_val = rec.get(alias)
                if field_val is not None:
                    break
        if field_val is None:
            if op == "ne":
                filtered.append(rec)  # missing field != value
            continue

        try:
            if _match_op(str(field_val), op, value):
                filtered.append(rec)
        except (TypeError, ValueError):
            if op == "ne":
                filtered.append(rec)
            continue

    return filtered


_FIELD_ALIASES: dict[str, list[str]] = {
    "price": ["cost", "Price", "Cost", "avg_price"],
    "type": ["category", "Type", "Category"],
    "name": ["Name", "poi_name"],
    "cuisine": ["Cuisine", "recommendedfood"],
}


def _match_op(field_val: str, op: str, value: Any) -> bool:
    """Apply a single comparison operator between a string field and a value."""
    if op == "eq":
        return field_val == str(value)
    elif op == "ne":
        return field_val != str(value)
    elif op == "contains":
        return str(value).lower() in field_val.lower()
    elif op in ("le", "lt", "ge", "gt"):
        try:
            fv = float(field_val)
            v = float(value)
            if op == "le":
                return fv <= v
            elif op == "lt":
                return fv < v
            elif op == "ge":
                return fv >= v
            elif op == "gt":
                return fv > v
        except (TypeError, ValueError):
            return False
    return True


def _covered_categories(tool_name: str) -> set[str]:
    """Which data categories does a successful query cover?"""
    mapping: dict[str, list[str]] = {
        "attractions_select": ["attractions"],
        "attractions_types": ["attractions"],
        "attractions_nearby": ["attractions"],
        "accommodations_select": ["accommodations"],
        "accommodations_nearby": ["accommodations"],
        "restaurants_select": ["restaurants"],
        "restaurants_nearby": ["restaurants"],
        "restaurants_cuisine": ["restaurants"],
    }
    return set(mapping.get(tool_name, []))


def _category_tool_map(category: str) -> list[str]:
    """Which tool_names can produce data for a given fetched_data category?"""
    mapping: dict[str, list[str]] = {
        "attractions": ["attractions_select", "attractions_types", "attractions_nearby"],
        "accommodations": ["accommodations_select", "accommodations_nearby"],
        "restaurants": ["restaurants_select", "restaurants_nearby", "restaurants_cuisine"],
    }
    return mapping.get(category, [])


def _populate_from_actions(
    fetched_data: dict[str, Any],
    action_results: dict[str, dict[str, Any]],
    category: str,
    data_key: str,
    count_key: str,
) -> int:
    """Populate fetched_data[data_key] from the largest-matching action result.

    Returns the total record count, or 0 if no results.
    """
    tool_names = _category_tool_map(category)
    candidates = [
        (ar["record_count"], ar["data"])
        for ar in action_results.values()
        if ar["tool_name"] in tool_names and isinstance(ar["data"], list)
    ]
    if candidates:
        candidates.sort(key=lambda x: -x[0])
        data = candidates[0][1]
        fetched_data[data_key] = data
        fetched_data[count_key] = len(data)
        return len(data)
    else:
        fetched_data[data_key] = []
        fetched_data[count_key] = 0
        return 0


def _fill_category(
    fetched_data: dict[str, Any],
    action_results: dict[str, dict[str, Any]],
    covered_data: set[str],
    db: TravelDatabase,
    target_city: str,
    *,
    category_key: str,
    data_key: str,
    count_key: str,
    db_category: str,
    source_key: str,
) -> None:
    """Fill one data category: action results first, fall back to full scan."""
    if category_key in covered_data:
        count = _populate_from_actions(fetched_data, action_results, category_key, data_key, count_key)
        if count > 0:
            fetched_data[source_key] = "action_results"
            return
        # action result was empty — fall through to full scan
    # Full scan fallback
    records = db.search_pois(target_city, filters={"category": db_category})
    fetched_data[data_key] = records
    fetched_data[count_key] = len(records)
    fetched_data[source_key] = "full_scan_fallback"


# ---------------------------------------------------------------------------
# Helper functions (preserved from original)
# ---------------------------------------------------------------------------

def _extract_card_values(cards: list[ConstraintCard], param_name: str) -> list[str]:
    values: list[str] = []
    for card in cards:
        value = (card.parameters or {}).get(param_name)
        if value and str(value) not in values:
            values.append(str(value))
    return values


def _extract_must_visit(cards: list[ConstraintCard]) -> list[str]:
    names: list[str] = []
    for card in cards:
        if card.category == "attraction" and card.parameters.get("must_visit_poi"):
            names.append(card.parameters["must_visit_poi"])
    return names


def _fetch_anchor_pois(
    constraints: Constraints,
    db: TravelDatabase,
    city: str,
) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    for card in constraints.cards:
        if card.category != "spatial":
            continue
        anchor_name = card.parameters.get("anchor_poi")
        if not anchor_name:
            continue
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


def _resolve_must_visit(
    names: list[str],
    pois: list[dict],
    db: TravelDatabase,
    city: str,
) -> list[dict[str, Any]]:
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
    return any(c.category == "budget" for c in cards)


def _compute_price_stats(fetched_data: dict[str, Any]) -> dict[str, Any]:
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
    people = people_number or 1
    return [
        {"mode": "airplane", "from": start_city, "to": target_city, "people": people, "estimated_cost_per_person": 800},
        {"mode": "train", "from": start_city, "to": target_city, "people": people, "estimated_cost_per_person": 400},
        {"mode": "metro", "scope": "innercity", "estimated_cost_per_person": 5},
        {"mode": "taxi", "scope": "innercity", "estimated_cost_per_taxi": 30, "people_per_taxi": 4},
    ]
