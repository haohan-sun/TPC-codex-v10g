"""约束卡片抽取主入口。"""

from __future__ import annotations

from src.constraints.constraint_card import build_constraint_card, merge_cards
from src.constraints.constraint_validator import validate_constraints
from src.constraints.hard_logic_parser import parse_hard_logic_snippets
from src.constraints.local_intent_parser import get_default_parser, LocalIntentParser
from src.data_layer.schema import ConstraintCard, Constraints, Query

# 默认使用 RuleIntentParser（离线，基于 lexicons/ 词典）
_nl_parser: LocalIntentParser | None = None


def _get_nl_parser() -> LocalIntentParser:
    global _nl_parser
    if _nl_parser is None:
        _nl_parser = get_default_parser()
    return _nl_parser


def parse_constraints(query: Query) -> Constraints:
    """将自然语言 query 解析为约束卡片集合。

    流程：
        1. 从 metadata 提取结构化全局参数（ChinaTravel 字段）；
        2. 解析 hard_logic_py DSL 为硬约束卡片；
        3. 从 nature_language 补充软/硬约束；
        4. 合并去重；
        5. 基本校验，问题写入 global_params["validation_issues"]。

    输入: Query（由 data_layer.loaders 加载）
    输出: Constraints（供 main.py 后续各阶段使用）

    Args:
        query: 用户原始查询。

    Returns:
        Constraints: 结构化约束集合。
    """
    meta = query.metadata or {}
    cards: list[ConstraintCard] = []

    # --- 1. 基础全局约束卡片（来自结构化字段） ---
    start_city = meta.get("start_city", "")
    target_city = meta.get("target_city", "")
    days = meta.get("days")
    people_number = meta.get("people_number")

    if start_city:
        cards.append(
            build_constraint_card(
                category="spatial",
                description=f"出发城市: {start_city}",
                parameters={"city": start_city, "role": "start"},
                is_hard=True,
                source="metadata",
                priority=5,
                card_id="meta_start_city",
            )
        )
    if target_city:
        cards.append(
            build_constraint_card(
                category="spatial",
                description=f"目的城市: {target_city}",
                parameters={"city": target_city, "role": "target"},
                is_hard=True,
                source="metadata",
                priority=5,
                card_id="meta_target_city",
            )
        )
    if days is not None:
        cards.append(
            build_constraint_card(
                category="temporal",
                description=f"行程 {days} 天",
                parameters={"days": int(days)},
                is_hard=True,
                source="metadata",
                priority=5,
                card_id="meta_days",
            )
        )
    if people_number is not None:
        cards.append(
            build_constraint_card(
                category="people",
                description=f"出行 {people_number} 人",
                parameters={"people_number": int(people_number)},
                is_hard=True,
                source="metadata",
                priority=5,
                card_id="meta_people",
            )
        )

    # --- 2. 解析 hard_logic_py ---
    hard_logic = meta.get("hard_logic_py") or []
    if isinstance(hard_logic, list):
        cards.extend(parse_hard_logic_snippets(hard_logic, start_index=len(cards)))

    # --- 3. 自然语言补充 ---
    nl_text = query.raw_text or meta.get("nature_language", "")
    cards.extend(_get_nl_parser().parse(nl_text))

    # --- 4. 合并去重 ---
    merged_cards = merge_cards(cards)

    # --- 5. 组装 global_params ---
    global_params = {
        "query_id": query.query_id,
        "start_city": start_city,
        "target_city": target_city,
        "days": int(days) if days is not None else None,
        "people_number": int(people_number) if people_number is not None else None,
        "tag": meta.get("tag"),
        "hard_logic_py": hard_logic,
        "nature_language": nl_text,
    }

    constraints = Constraints(
        query_id=query.query_id,
        cards=merged_cards,
        global_params=global_params,
    )

    # --- 6. 校验并记录问题 ---
    issues = validate_constraints(constraints)
    if issues:
        constraints.global_params["validation_issues"] = issues

    return constraints
