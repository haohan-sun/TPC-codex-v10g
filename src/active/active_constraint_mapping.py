"""Active Constraint Mapping — 升级版 Active SLAM。

核心循环:
    1. init_beliefs         — 从 constraints + risk_profile 建立 belief state
    2. generate_actions      — 按约束维度生成候选 active action
    3. estimate_info_gain    — 计算每个 action 的期望信息增益
    4. estimate_query_cost   — 估算查询代价
    5. select_actions        — 按 priority_score = info_gain / cost 选 top-K
    6. explain_selection     — 生成人类可读的"为什么查/不查"解释
    7. update_beliefs        — 执行查询后更新 belief state

与 agent_env structured tools 的映射:
    spatial        → accommodations_nearby / poi_lat_lon_search
    budget         → accommodations_select / restaurants_select
    accommodation  → accommodations_select / accommodations_nearby
    transport      → intercity_transport_select / goto
    attraction     → attractions_select / attractions_types
    dietary        → restaurants_select / restaurants_cuisine
"""

from __future__ import annotations

from typing import Any

from src.data_layer.schema import (
    ActionSelectionResult,
    ActiveAction,
    ActiveInfo,
    ConstraintBelief,
    ConstraintCard,
    Constraints,
    RiskProfile,
)

# ---------------------------------------------------------------------------
# Constraint category → agent_env structured tools
# ---------------------------------------------------------------------------

CATEGORY_TO_TOOLS: dict[str, list[dict[str, Any]]] = {
    "spatial": [
        {"tool": "accommodations_nearby", "output_keys": ["name", "lat", "lon", "price", "distance"]},
        {"tool": "poi_lat_lon_search", "output_keys": ["lat", "lon"]},
    ],
    "budget": [
        {"tool": "accommodations_select", "output_keys": ["name", "price"]},
        {"tool": "restaurants_select", "output_keys": ["name", "price", "cuisine"]},
    ],
    "accommodation": [
        {"tool": "accommodations_select", "output_keys": ["name", "price", "featurehoteltype"]},
        {"tool": "accommodations_nearby", "output_keys": ["name", "lat", "lon", "price", "distance"]},
    ],
    "transport": [
        {"tool": "intercity_transport_select", "output_keys": ["TrainID", "FlightID", "BeginTime", "EndTime", "Cost"]},
        {"tool": "goto", "output_keys": ["start", "end", "mode", "start_time", "end_time", "cost", "distance"]},
    ],
    "attraction": [
        {"tool": "attractions_select", "output_keys": ["name", "type", "price", "opentime", "endtime"]},
        {"tool": "attractions_types", "output_keys": ["types"]},
    ],
    "dietary": [
        {"tool": "restaurants_select", "output_keys": ["name", "price", "cuisine"]},
        {"tool": "restaurants_cuisine", "output_keys": ["cuisines"]},
    ],
    "ticket": [],       # derived from people count, no data query needed
    "temporal": [],     # derived from days metadata
    "people": [],       # derived from people_number
    "preference": [],   # soft preference, no urgent data query
    "logic": [],        # needs constraint parser improvement, not data
}

# 各类约束的严重程度（与 constraint_risk_estimator 一致）
CATEGORY_SEVERITY: dict[str, float] = {
    "logic": 0.95,
    "budget": 0.90,
    "spatial": 0.85,
    "transport": 0.85,
    "accommodation": 0.80,
    "ticket": 0.80,
    "temporal": 0.75,
    "people": 0.75,
    "attraction": 0.70,
    "dietary": 0.50,
    "preference": 0.40,
}

# 各种查询的基础代价（估算毫秒）
BASE_QUERY_COST_MS: dict[str, float] = {
    "accommodations_nearby": 80,
    "poi_lat_lon_search": 30,
    "accommodations_select": 60,
    "restaurants_select": 60,
    "attractions_select": 60,
    "attractions_types": 20,
    "restaurants_cuisine": 20,
    "intercity_transport_select": 100,
    "goto": 80,
}


# ---------------------------------------------------------------------------
# 1. Belief state initialization
# ---------------------------------------------------------------------------

def init_beliefs(constraints: Constraints, risk_profile: RiskProfile) -> dict[str, ConstraintBelief]:
    """从约束卡片和风险画像建立初始 belief state。"""
    beliefs: dict[str, ConstraintBelief] = {}

    for card in constraints.cards:
        cat = card.category
        severity = CATEGORY_SEVERITY.get(cat, 0.5)
        risk = risk_profile.risk_scores.get(cat, severity * 0.5)

        if cat not in beliefs:
            beliefs[cat] = ConstraintBelief(category=cat)

        belief = beliefs[cat]
        belief.risk_level = max(belief.risk_level, risk)

        # 判断缺失数据
        params = card.parameters or {}
        if cat == "spatial" and params.get("anchor_poi") and not params.get("anchor_resolved"):
            belief.missing_data.append("anchor_coordinates")
        if cat == "budget" and params.get("max_cost") is not None:
            belief.missing_data.append("price_data")
        if cat == "accommodation" and params.get("required_type") and not params.get("type_resolved"):
            belief.missing_data.append("hotel_features")
        if cat == "transport" and params.get("intercity_mode"):
            belief.missing_data.append("intercity_options")
        if cat == "attraction":
            if params.get("must_visit_poi") and not params.get("poi_resolved"):
                belief.missing_data.append("must_visit_poi_data")
            if params.get("forbidden_attraction_type"):
                belief.missing_data.append("attraction_types")
        if cat == "dietary":
            if params.get("cuisine_preference"):
                belief.missing_data.append("cuisine_data")

        # 初始置信度
        if not belief.missing_data:
            belief.confidence = 0.8
            belief.resolved = True
        elif len(belief.missing_data) <= 1:
            belief.confidence = 0.4
        else:
            belief.confidence = 0.2

    # 确保高风险维度有 entry
    for cat, score in risk_profile.risk_scores.items():
        if cat not in beliefs and score >= 0.4:
            beliefs[cat] = ConstraintBelief(
                category=cat,
                risk_level=score,
                confidence=0.3,
                missing_data=["general_data"],
            )

    return beliefs


# ---------------------------------------------------------------------------
# 2. Candidate action generation
# ---------------------------------------------------------------------------

def generate_candidate_actions(
    beliefs: dict[str, ConstraintBelief],
    constraints: Constraints,
) -> list[ActiveAction]:
    """为每个未解决的约束维度生成候选查询动作。"""
    actions: list[ActiveAction] = []
    gp = constraints.global_params
    target_city = str(gp.get("target_city") or "")
    start_city = str(gp.get("start_city") or "")
    action_idx = 0

    for cat, belief in beliefs.items():
        if belief.resolved and belief.confidence >= 0.7:
            continue
        tool_specs = CATEGORY_TO_TOOLS.get(cat, [])
        if not tool_specs:
            continue

        for spec in tool_specs:
            params = _build_tool_params(cat, spec["tool"], constraints, target_city, start_city)
            if not params:
                continue

            action = ActiveAction(
                action_id=f"acm_{action_idx}",
                tool_name=spec["tool"],
                params=params,
                target_category=cat,
                risk_reason=_risk_reason(cat, belief, constraints),
                expected_output_keys=list(spec.get("output_keys", [])),
            )
            actions.append(action)
            action_idx += 1

    return actions


def _build_tool_params(
    category: str,
    tool_name: str,
    constraints: Constraints,
    target_city: str,
    start_city: str,
) -> dict[str, Any] | None:
    """根据约束卡片为 tool 构造参数。"""
    cards = [c for c in constraints.cards if c.category == category]
    params: dict[str, Any] = {}

    if tool_name == "accommodations_nearby":
        anchor = _find_param(cards, "anchor_poi")
        dist = _find_param(cards, "max_distance_km")
        if not anchor:
            return None
        params = {"city": target_city, "point": anchor, "topk": 10, "dist": float(dist or 8.0)}

    elif tool_name == "poi_lat_lon_search":
        anchor = _find_param(cards, "anchor_poi") or _find_param(cards, "must_visit_poi")
        if not anchor:
            return None
        params = {"city": target_city, "name": anchor}

    elif tool_name == "accommodations_select":
        budget_val = _find_param(cards, "max_cost")
        required_type = _find_param(cards, "required_type")
        if budget_val is not None:
            params = {"city": target_city, "key": "price", "op": "le", "value": float(budget_val)}
        elif required_type:
            params = {"city": target_city, "key": "name", "op": "ne", "value": ""}
        else:
            params = {"city": target_city, "key": "name", "op": "ne", "value": ""}

    elif tool_name == "restaurants_select":
        budget_val = _find_param(cards, "max_cost")
        if budget_val is not None:
            params = {"city": target_city, "key": "price", "op": "le", "value": float(budget_val)}
        else:
            params = {"city": target_city, "key": "name", "op": "ne", "value": ""}

    elif tool_name == "restaurants_cuisine":
        params = {"city": target_city}

    elif tool_name == "intercity_transport_select":
        mode = _find_param(cards, "intercity_mode") or "train"
        if not start_city or not target_city:
            return None
        params = {"start_city": start_city, "end_city": target_city, "intercity_type": mode, "earliest_leave_time": "06:00"}

    elif tool_name == "goto":
        anchor = _find_param(cards, "anchor_poi")
        must_visit = _find_param(cards, "must_visit_poi")
        point = anchor or must_visit
        if not point:
            return None
        params = {"city": target_city, "start": f"{target_city} Station", "end": point, "start_time": "09:00", "transport_type": "metro"}

    elif tool_name == "attractions_select":
        must_visit = _find_param(cards, "must_visit_poi")
        forbidden_type = _find_param(cards, "forbidden_attraction_type")
        must_type = _find_param(cards, "must_visit_type")
        if must_visit:
            params = {"city": target_city, "key": "name", "op": "contains", "value": must_visit}
        elif must_type:
            params = {"city": target_city, "key": "type", "op": "contains", "value": must_type}
        elif forbidden_type:
            params = {"city": target_city, "key": "type", "op": "ne", "value": forbidden_type}
        else:
            params = {"city": target_city, "key": "name", "op": "ne", "value": ""}

    elif tool_name == "attractions_types":
        params = {"city": target_city}

    else:
        return None

    if "city" not in params and target_city:
        params["city"] = target_city
    return params


def _find_param(cards: list[ConstraintCard], key: str) -> Any | None:
    for card in cards:
        val = (card.parameters or {}).get(key)
        if val is not None:
            return val
    return None


def _risk_reason(cat: str, belief: ConstraintBelief, constraints: Constraints) -> str:
    cards = [c for c in constraints.cards if c.category == cat]
    missing = ", ".join(belief.missing_data[:3]) if belief.missing_data else "数据不完整"
    return f"[{cat}] risk={belief.risk_level:.2f}, confidence={belief.confidence:.2f}, missing=({missing})"


# ---------------------------------------------------------------------------
# 3. Information gain estimation
# ---------------------------------------------------------------------------

def estimate_info_gain(action: ActiveAction, beliefs: dict[str, ConstraintBelief]) -> float:
    """估算执行该 action 的期望信息增益 (0~1)。

    info_gain = 当前不确定性 × 约束严重度 × 工具覆盖度
    """
    belief = beliefs.get(action.target_category)
    if not belief:
        return 0.0

    # 当前不确定性 = 1 - confidence
    uncertainty = max(0.0, 1.0 - belief.confidence)

    # 严重度
    severity = CATEGORY_SEVERITY.get(action.target_category, 0.5)

    # 工具覆盖度：该 tool 能覆盖 missing_data 中多少项
    coverage = _tool_coverage(action.tool_name, belief.missing_data)

    # 如果 confidence 已经很高，收益低
    if belief.resolved and belief.confidence > 0.8:
        return 0.0

    gain = uncertainty * severity * coverage
    return round(min(1.0, gain), 4)


def _tool_coverage(tool_name: str, missing_data: list[str]) -> float:
    """工具对缺失数据类型的覆盖度。"""
    covers: dict[str, list[str]] = {
        "accommodations_nearby": ["anchor_coordinates", "hotel_features", "general_data"],
        "poi_lat_lon_search": ["anchor_coordinates", "must_visit_poi_data"],
        "accommodations_select": ["price_data", "hotel_features", "general_data"],
        "restaurants_select": ["price_data", "cuisine_data", "general_data"],
        "restaurants_cuisine": ["cuisine_data", "general_data"],
        "intercity_transport_select": ["intercity_options", "general_data"],
        "goto": ["anchor_coordinates", "general_data"],
        "attractions_select": ["must_visit_poi_data", "attraction_types", "general_data"],
        "attractions_types": ["attraction_types", "general_data"],
    }
    covered = covers.get(tool_name, [])
    if not missing_data:
        return 0.5  # 没有明确的缺失项，中性覆盖
    hits = sum(1 for m in missing_data if any(c in m for c in covered))
    return max(0.2, hits / max(1, len(missing_data)))


# ---------------------------------------------------------------------------
# 4. Query cost estimation
# ---------------------------------------------------------------------------

def estimate_query_cost(action: ActiveAction) -> float:
    """估算查询代价 (0~1 normalized)。

    cost 综合考虑:
        - 基础查询时间
        - 结果规模（topk 越大越贵）
        - 对规划的扰动（数据越多后续处理越重）
    """
    base = BASE_QUERY_COST_MS.get(action.tool_name, 50.0)
    # topk 惩罚
    topk = action.params.get("topk", 10)
    if topk > 10:
        base *= 1.0 + 0.05 * (topk - 10)
    # normalize to 0~1 (max ~200ms)
    return round(min(1.0, base / 200.0), 4)


# ---------------------------------------------------------------------------
# 5. Action selection
# ---------------------------------------------------------------------------

def select_actions(
    actions: list[ActiveAction],
    beliefs: dict[str, ConstraintBelief],
    max_actions: int = 6,
) -> tuple[list[ActiveAction], list[ActiveAction]]:
    """按 priority_score = info_gain / (cost + ε) 选择 top-K 动作。

    Returns:
        (selected, rejected) — 均为带 explanation 的 ActiveAction 列表。
    """
    scored: list[ActiveAction] = []
    for action in actions:
        action.expected_info_gain = estimate_info_gain(action, beliefs)
        action.query_cost = estimate_query_cost(action)
        epsilon = 0.01  # 避免除零
        action.priority_score = round(action.expected_info_gain / (action.query_cost + epsilon), 4)

        # 阈值：info_gain < 0.05 的查询不值得做
        if action.expected_info_gain < 0.03:
            action.selected = False
            action.selection_reason = f"信息增益过低 ({action.expected_info_gain:.3f})，不值得查询"
        else:
            scored.append(action)

    # 按 priority_score 降序排列
    scored.sort(key=lambda a: (-a.priority_score, -a.expected_info_gain))

    selected = scored[:max_actions]
    rejected = scored[max_actions:]

    for a in selected:
        a.selected = True
        a.selection_reason = (
            f"选中: priority={a.priority_score:.3f} "
            f"(gain={a.expected_info_gain:.3f}, cost={a.query_cost:.3f}) "
            f"→ 解决 {a.target_category} 维度 {a.risk_reason}"
        )
    for a in rejected:
        a.selected = False
        if a.expected_info_gain < 0.05:
            a.selection_reason = f"信息增益过低 ({a.expected_info_gain:.3f})"
        else:
            a.selection_reason = (
                f"优先级不足: priority={a.priority_score:.3f} "
                f"(前{max_actions}个 action 已覆盖更高风险维度)"
            )

    # 找到被"未生成"的维度（没有对应 action 或 action gain 太低）
    return selected, rejected


# ---------------------------------------------------------------------------
# 6. Explanation generation
# ---------------------------------------------------------------------------

def explain_selection(
    selected: list[ActiveAction],
    rejected: list[ActiveAction],
    beliefs: dict[str, ConstraintBelief],
) -> list[str]:
    """生成人类可读的查询解释。"""
    lines: list[str] = []

    lines.append(f"=== Active Constraint Mapping 查询解释 ===")
    lines.append(f"  Belief dimensions: {len(beliefs)}")
    unresolved = {cat: b for cat, b in beliefs.items() if not b.resolved}
    lines.append(f"  未解决维度: {len(unresolved)} — {list(unresolved.keys())}")
    lines.append("")

    if selected:
        lines.append(f"--- 选中 {len(selected)} 条查询 ---")
        for a in selected:
            lines.append(
                f"  ✓ {a.tool_name}({_fmt_params(a.params)}) "
                f"| gain={a.expected_info_gain:.3f} cost={a.query_cost:.3f} "
                f"| reason: {a.selection_reason}"
            )
    else:
        lines.append("  (无选中查询 — 所有维度置信度足够或信息增益过低)")

    if rejected:
        lines.append(f"\n--- 拒绝 {len(rejected)} 条查询 ---")
        for a in rejected:
            lines.append(
                f"  ✗ {a.tool_name}({_fmt_params(a.params)}) "
                f"| gain={a.expected_info_gain:.3f} cost={a.query_cost:.3f} "
                f"| reason: {a.selection_reason}"
            )

    # 未覆盖维度
    covered_cats = set(a.target_category for a in selected)
    uncovered = [cat for cat, b in beliefs.items() if cat not in covered_cats and not b.resolved]
    if uncovered:
        lines.append(f"\n--- 未覆盖的高不确定性维度 ---")
        for cat in uncovered:
            b = beliefs[cat]
            lines.append(
                f"  ? {cat}: risk={b.risk_level:.2f}, confidence={b.confidence:.2f}, "
                f"missing={b.missing_data[:2]} — 无适合的查询工具或信息增益过低"
            )

    return lines


def _fmt_params(params: dict[str, Any]) -> str:
    parts = []
    for k, v in params.items():
        s = str(v)
        if len(s) > 20:
            s = s[:17] + "..."
        parts.append(f"{k}={s}")
    return ", ".join(parts[:4])


# ---------------------------------------------------------------------------
# 7. Belief update
# ---------------------------------------------------------------------------

def update_beliefs(
    beliefs: dict[str, ConstraintBelief],
    executed_actions: list[ActiveAction],
    query_results: dict[str, Any],
) -> dict[str, ConstraintBelief]:
    """执行查询后更新 belief state。

    Args:
        beliefs: 当前 belief state (会被原地修改)。
        executed_actions: 已执行的 ActiveAction 列表。
        query_results: tool_name → result data 映射。

    Returns:
        更新后的 beliefs。
    """
    for action in executed_actions:
        cat = action.target_category
        if cat not in beliefs:
            continue
        belief = beliefs[cat]

        result = query_results.get(action.tool_name)
        has_data = result is not None and (
            (isinstance(result, list) and len(result) > 0) or
            (isinstance(result, dict) and len(result) > 0)
        )

        if has_data:
            # 数据返回 → 提升置信度，标记缺失项为已补全
            belief.confidence = min(1.0, belief.confidence + 0.4)
            belief.missing_data = [
                m for m in belief.missing_data
                if not _data_covers_missing(action.tool_name, m)
            ]
            belief.last_query_result = {
                "tool": action.tool_name,
                "record_count": len(result) if isinstance(result, list) else 1,
            }
        else:
            # 无数据返回 → 置信度小幅提升（确认了"查不到"也是一种信息）
            belief.confidence = min(1.0, belief.confidence + 0.1)

        if not belief.missing_data and belief.confidence >= 0.7:
            belief.resolved = True
        if belief.confidence >= 0.85:
            belief.resolved = True

    return beliefs


def _data_covers_missing(tool_name: str, missing_item: str) -> bool:
    covers: dict[str, list[str]] = {
        "accommodations_nearby": ["anchor_coordinates", "general_data"],
        "poi_lat_lon_search": ["anchor_coordinates"],
        "accommodations_select": ["price_data", "hotel_features", "general_data"],
        "restaurants_select": ["price_data", "cuisine_data", "general_data"],
        "restaurants_cuisine": ["cuisine_data"],
        "intercity_transport_select": ["intercity_options"],
        "goto": ["anchor_coordinates"],
        "attractions_select": ["must_visit_poi_data", "attraction_types", "general_data"],
        "attractions_types": ["attraction_types"],
    }
    covered = covers.get(tool_name, [])
    return any(c in missing_item for c in covered)


# ---------------------------------------------------------------------------
# 8. Top-level entry point (replaces old active_query_selector logic)
# ---------------------------------------------------------------------------

def active_constraint_mapping(
    constraints: Constraints,
    risk_profile: RiskProfile,
    max_actions: int = 6,
) -> ActionSelectionResult:
    """Active Constraint Mapping 主入口。

    执行完整的 belief → action generation → scoring → selection → explanation 流程。
    不执行实际查询（由调用方使用 agent_env 或 SandboxClient 执行）。

    Returns:
        ActionSelectionResult: 含 beliefs, selected/rejected actions, explanations。
    """
    # 1. 初始化 belief state
    beliefs = init_beliefs(constraints, risk_profile)

    # 2. 生成候选动作
    all_actions = generate_candidate_actions(beliefs, constraints)

    # 3-4. info_gain / cost 在 select_actions 中计算
    # 5. 选择动作
    selected, rejected = select_actions(all_actions, beliefs, max_actions=max_actions)

    # 6. 生成解释
    explanations = explain_selection(selected, rejected, beliefs)

    total_gain = sum(a.expected_info_gain for a in selected)
    total_cost = sum(a.query_cost for a in selected)

    return ActionSelectionResult(
        query_id=constraints.query_id,
        beliefs=beliefs,
        all_actions=all_actions,
        selected_actions=selected,
        rejected_actions=rejected,
        total_expected_gain=round(total_gain, 4),
        total_query_cost=round(total_cost, 4),
        explanation_summary=explanations,
    )
