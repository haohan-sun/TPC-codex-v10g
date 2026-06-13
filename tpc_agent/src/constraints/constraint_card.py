"""约束卡片构建与合并。"""

from __future__ import annotations

import hashlib

from src.data_layer.schema import ConstraintCard


def build_constraint_card(
    category: str,
    description: str,
    parameters: dict | None = None,
    is_hard: bool = True,
    source: str = "user",
    priority: int = 1,
    card_id: str | None = None,
) -> ConstraintCard:
    """构建单张约束卡片。

    Args:
        category: 约束类别（temporal/budget/spatial/transport 等）。
        description: 自然语言描述，便于调试与展示。
        parameters: 结构化参数，供下游规划模块直接使用。
        is_hard: True=硬约束（必须满足），False=软约束（偏好）。
        source: 来源标记（user / hard_logic_py / nature_language）。
        priority: 优先级，数值越大越重要。
        card_id: 可选自定义 ID；未提供时自动生成。

    Returns:
        ConstraintCard: 约束卡片实例。
    """
    params = dict(parameters or {})
    if card_id is None:
        digest = hashlib.md5(f"{category}:{description}:{params}".encode()).hexdigest()[:8]
        card_id = f"{category}_{digest}"

    return ConstraintCard(
        card_id=card_id,
        category=category,
        description=description,
        parameters=params,
        priority=priority,
        is_hard=is_hard,
        source=source,
    )


def merge_cards(cards: list[ConstraintCard]) -> list[ConstraintCard]:
    """合并去重约束卡片。

    去重规则：
        1. 相同 card_id 保留优先级更高者；
        2. 硬约束卡片与同类硬约束参数完全一致时合并；
        3. 软约束（preference/dietary）允许共存。

    Args:
        cards: 原始卡片列表。

    Returns:
        list[ConstraintCard]: 去重后的卡片，按 priority 降序排列。
    """
    by_id: dict[str, ConstraintCard] = {}
    signature_index: dict[str, str] = {}

    for card in cards:
        # 规则 1：card_id 冲突
        if card.card_id in by_id:
            existing = by_id[card.card_id]
            if card.priority > existing.priority:
                by_id[card.card_id] = card
            continue

        # 规则 2：硬约束语义重复（同 category + 核心参数）
        if card.is_hard:
            sig = _card_signature(card)
            if sig in signature_index:
                existing_id = signature_index[sig]
                existing = by_id[existing_id]
                if card.priority > existing.priority:
                    del by_id[existing_id]
                    by_id[card.card_id] = card
                    signature_index[sig] = card.card_id
                continue
            signature_index[sig] = card.card_id

        by_id[card.card_id] = card

    merged = sorted(by_id.values(), key=lambda c: (-c.priority, c.category, c.card_id))
    return merged


def _card_signature(card: ConstraintCard) -> str:
    """生成用于去重的卡片签名（忽略 dsl 原文差异）。"""
    params = {k: v for k, v in card.parameters.items() if k != "dsl"}
    return f"{card.category}|{card.is_hard}|{sorted(params.items())}"
