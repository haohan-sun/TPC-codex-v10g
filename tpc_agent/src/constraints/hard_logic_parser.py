"""hard_logic_py DSL 片段解析为约束卡片。"""

from __future__ import annotations

import re
from typing import Any

from src.constraints.constraint_card import build_constraint_card
from src.data_layer.schema import ConstraintCard


def parse_hard_logic_snippets(snippets: list[str], start_index: int = 0) -> list[ConstraintCard]:
    """将 hard_logic_py 代码片段列表解析为约束卡片。

    支持常见 ChinaTravel DSL 模式：
        - day_count / people_count
        - restaurant_cost / accommodation_cost 预算
        - poi_distance 空间约束
        - intercity_transport 城际交通
        - accommodation_type 酒店类型
        - activity_tickets / metro_tickets / taxi_cars 票务

    Args:
        snippets: hard_logic_py 字符串列表。
        start_index: 卡片 ID 起始序号。

    Returns:
        list[ConstraintCard]: 解析出的约束卡片。
    """
    cards: list[ConstraintCard] = []
    idx = start_index

    for snippet in snippets:
        if not snippet or not snippet.strip():
            continue

        parsed = _parse_single_snippet(snippet.strip(), idx)
        cards.extend(parsed)
        idx += len(parsed)

    return cards


def _parse_single_snippet(snippet: str, base_idx: int) -> list[ConstraintCard]:
    """解析单条 DSL 片段，可能产生 0~N 张卡片。"""
    cards: list[ConstraintCard] = []
    local_idx = base_idx

    # 1) 天数约束: result=(day_count(plan)==3)
    day_match = re.search(r"day_count\(plan\)\s*==\s*(\d+)", snippet)
    if day_match:
        days = int(day_match.group(1))
        cards.append(
            build_constraint_card(
                category="temporal",
                description=f"行程天数必须为 {days} 天",
                parameters={"days": days, "dsl": snippet},
                is_hard=True,
                source="hard_logic_py",
                card_id=f"hard_{local_idx}",
            )
        )
        local_idx += 1

    # 2) 人数约束: result=(people_count(plan)==5)
    people_match = re.search(r"people_count\(plan\)\s*==\s*(\d+)", snippet)
    if people_match:
        people = int(people_match.group(1))
        cards.append(
            build_constraint_card(
                category="people",
                description=f"出行人数必须为 {people} 人",
                parameters={"people_number": people, "dsl": snippet},
                is_hard=True,
                source="hard_logic_py",
                card_id=f"hard_{local_idx}",
            )
        )
        local_idx += 1

    # 3) 餐饮预算: restaurant_cost<=1800
    dining_budget = re.search(r"restaurant_cost\s*<=\s*([\d.]+)", snippet)
    if dining_budget:
        amount = float(dining_budget.group(1))
        cards.append(
            build_constraint_card(
                category="budget",
                description=f"餐饮总预算不超过 {amount}",
                parameters={"budget_type": "dining", "max_cost": amount, "dsl": snippet},
                is_hard=True,
                source="hard_logic_py",
                card_id=f"hard_{local_idx}",
            )
        )
        local_idx += 1

    # 4) 住宿预算: accommodation_cost<=800
    hotel_budget = re.search(r"accommodation_cost\s*<=\s*([\d.]+)", snippet)
    if hotel_budget:
        amount = float(hotel_budget.group(1))
        cards.append(
            build_constraint_card(
                category="budget",
                description=f"住宿总预算不超过 {amount}",
                parameters={"budget_type": "accommodation", "max_cost": amount, "dsl": snippet},
                is_hard=True,
                source="hard_logic_py",
                card_id=f"hard_{local_idx}",
            )
        )
        local_idx += 1

    # 5) 空间约束: poi_distance(..., 'East Lake Park', ...)<=8.51
    distance_match = re.search(
        r"poi_distance\([^,]+,\s*['\"]([^'\"]+)['\"],\s*[^)]+\)\s*<=\s*([\d.]+)",
        snippet,
    )
    if distance_match:
        landmark = distance_match.group(1)
        max_dist = float(distance_match.group(2))
        cards.append(
            build_constraint_card(
                category="spatial",
                description=f"住宿位置距 {landmark} 不超过 {max_dist} km",
                parameters={
                    "anchor_poi": landmark,
                    "max_distance_km": max_dist,
                    "target": "accommodation",
                    "dsl": snippet,
                },
                is_hard=True,
                source="hard_logic_py",
                card_id=f"hard_{local_idx}",
            )
        )
        local_idx += 1

    # 6) 城际交通方式（飞机往返等）
    if "intercity_transport" in snippet and "airplane" in snippet:
        cards.append(
            build_constraint_card(
                category="transport",
                description="城际交通需使用飞机（含去程/返程规则）",
                parameters={"intercity_mode": "airplane", "dsl": snippet},
                is_hard=True,
                source="hard_logic_py",
                card_id=f"hard_{local_idx}",
            )
        )
        local_idx += 1
    elif "intercity_transport" in snippet and "train" in snippet:
        cards.append(
            build_constraint_card(
                category="transport",
                description="城际交通需使用火车",
                parameters={"intercity_mode": "train", "dsl": snippet},
                is_hard=True,
                source="hard_logic_py",
                card_id=f"hard_{local_idx}",
            )
        )
        local_idx += 1

    # 7) 酒店类型约束: {"Free parking"}&accommodation_type_set
    hotel_type_match = re.search(r"\{\"([^\"}]+)\"\}\s*&\s*accommodation_type_set", snippet)
    if hotel_type_match:
        hotel_type = hotel_type_match.group(1)
        cards.append(
            build_constraint_card(
                category="accommodation",
                description=f"住宿类型需包含: {hotel_type}",
                parameters={"required_type": hotel_type, "dsl": snippet},
                is_hard=True,
                source="hard_logic_py",
                card_id=f"hard_{local_idx}",
            )
        )
        local_idx += 1

    # 8) 票务与人数一致（attraction/airplane/train/metro）
    ticket_match = re.search(
        r"activity_tickets\(activity\)\s*!=\s*(\d+)", snippet
    )
    if ticket_match:
        count = int(ticket_match.group(1))
        cards.append(
            build_constraint_card(
                category="ticket",
                description=f"景点/城际票务数量需与人数一致（{count} 张）",
                parameters={"ticket_count": count, "scope": "activity", "dsl": snippet},
                is_hard=True,
                source="hard_logic_py",
                card_id=f"hard_{local_idx}",
            )
        )
        local_idx += 1

    metro_ticket = re.search(r"metro_tickets\([^)]+\)\s*!=\s*(\d+)", snippet)
    if metro_ticket:
        count = int(metro_ticket.group(1))
        cards.append(
            build_constraint_card(
                category="ticket",
                description=f"地铁票数量需为 {count}",
                parameters={"ticket_count": count, "scope": "metro", "dsl": snippet},
                is_hard=True,
                source="hard_logic_py",
                card_id=f"hard_{local_idx}",
            )
        )
        local_idx += 1

    taxi_match = re.search(r"taxi_cars\([^)]+\)\s*!=\s*(\d+)", snippet)
    if taxi_match:
        cars = int(taxi_match.group(1))
        cards.append(
            build_constraint_card(
                category="transport",
                description=f"出租车数量需为 {cars} 辆",
                parameters={"taxi_cars": cars, "dsl": snippet},
                is_hard=True,
                source="hard_logic_py",
                card_id=f"hard_{local_idx}",
            )
        )
        local_idx += 1

    # 9) 市内交通偏好：metro / taxi / walk
    if "innercity_transport_type" in snippet:
        for mode in ("metro", "taxi", "walk", "bus"):
            if f"'{mode}'" in snippet or f'"{mode}"' in snippet:
                cards.append(
                    build_constraint_card(
                        category="transport",
                        description=f"市内交通涉及 {mode} 方式",
                        parameters={"innercity_mode": mode, "dsl": snippet},
                        is_hard=True,
                        source="hard_logic_py",
                        card_id=f"hard_{local_idx}",
                    )
                )
                local_idx += 1
                break

    # 若未匹配任何规则，保留原始 DSL 供后续 LLM/规则扩展
    if not cards:
        cards.append(
            build_constraint_card(
                category="logic",
                description="未分类的逻辑约束（保留原始 DSL）",
                parameters={"dsl": snippet, "parsed": False},
                is_hard=True,
                source="hard_logic_py",
                card_id=f"hard_{local_idx}",
            )
        )

    return cards
