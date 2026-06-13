"""交通方式排序。"""

from __future__ import annotations

from typing import Any

from src.data_layer.schema import Constraints


def rank_transports(
    options: list[dict[str, Any]],
    constraints: Constraints,
) -> list[dict[str, Any]]:
    """按约束与成本对交通选项排序。

    排序规则：
        1. 硬约束指定的 intercity_mode / innercity_mode 优先；
        2. transport_weight 低时优先选省时/直达方案；
        3. 人数影响出租车数量约束。

    Args:
        options: 交通选项列表（通常来自 active_info.fetched_data["transports"]）。
        constraints: 约束集合。

    Returns:
        list[dict]: 按优先级排序的交通选项。
    """
    if not options:
        return _default_transports(constraints)

    required_intercity = _get_required_mode(constraints, "intercity_mode")
    required_innercity = _get_required_mode(constraints, "innercity_mode")
    people = constraints.global_params.get("people_number") or 1

    scored: list[tuple[float, dict[str, Any]]] = []
    for opt in options:
        score = 1.0
        mode = str(opt.get("mode", ""))

        if required_intercity and opt.get("scope") != "innercity":
            if mode == required_intercity:
                score += 5.0
            else:
                score -= 2.0

        if required_innercity and opt.get("scope") == "innercity":
            if mode == required_innercity:
                score += 3.0

        # 出租车：检查人数与车辆数约束
        if mode == "taxi":
            taxi_card = _get_taxi_constraint(constraints)
            if taxi_card:
                required_cars = taxi_card.parameters.get("taxi_cars")
                if required_cars:
                    score += 1.0 if required_cars == _calc_taxi_cars(people) else -1.0

        # 成本越低分越高（预算友好）
        cost = opt.get("estimated_cost_per_person") or opt.get("estimated_cost_per_taxi") or 0
        try:
            score += max(0, 2.0 - float(cost) / 500.0)
        except (TypeError, ValueError):
            pass

        scored.append((score, opt))

    scored.sort(key=lambda x: -x[0])
    return [opt for _, opt in scored]


def _get_required_mode(constraints: Constraints, param_key: str) -> str | None:
    for card in constraints.cards:
        if card.category == "transport" and card.parameters.get(param_key):
            return str(card.parameters[param_key])
    return None


def _get_taxi_constraint(constraints: Constraints):
    for card in constraints.cards:
        if card.category == "transport" and card.parameters.get("taxi_cars") is not None:
            return card
    return None


def _calc_taxi_cars(people: int) -> int:
    """按 4 人/车估算出租车数量。"""
    return max(1, (people + 3) // 4)


def _default_transports(constraints: Constraints) -> list[dict[str, Any]]:
    """无交通数据时返回基础默认选项。"""
    gp = constraints.global_params
    people = gp.get("people_number") or 1
    return [
        {"mode": "airplane", "from": gp.get("start_city"), "to": gp.get("target_city"), "people": people},
        {"mode": "train", "from": gp.get("start_city"), "to": gp.get("target_city"), "people": people},
        {"mode": "metro", "scope": "innercity"},
        {"mode": "taxi", "scope": "innercity"},
    ]
