"""自然语言补充约束解析。"""

from __future__ import annotations

import re

from src.constraints.constraint_card import build_constraint_card
from src.data_layer.schema import ConstraintCard


def parse_nature_language(text: str, start_index: int = 0) -> list[ConstraintCard]:
    """从 nature_language 中抽取软/硬约束补充信息。

    Args:
        text: 自然语言描述。
        start_index: 卡片 ID 起始序号。

    Returns:
        list[ConstraintCard]: 补充约束卡片（多为软约束）。
    """
    if not text or not text.strip():
        return []

    cards: list[ConstraintCard] = []
    idx = start_index
    lowered = text.lower()

    # 节奏偏好：不太累 / not too tired
    if any(kw in lowered for kw in ("not too tired", "不要太累", "轻松", "别太累", "不要太赶")):
        cards.append(
            build_constraint_card(
                category="preference",
                description="行程节奏偏轻松，不宜过度疲劳",
                parameters={"pace": "relaxed"},
                is_hard=False,
                source="nature_language",
                priority=2,
                card_id=f"nl_{idx}",
            )
        )
        idx += 1

    # 紧凑节奏
    if any(kw in lowered for kw in ("紧凑", "packed", "as many as possible", "尽量多")):
        cards.append(
            build_constraint_card(
                category="preference",
                description="行程节奏偏紧凑，尽量多安排活动",
                parameters={"pace": "intensive"},
                is_hard=False,
                source="nature_language",
                priority=2,
                card_id=f"nl_{idx}",
            )
        )
        idx += 1

    # 本地菜 / 特色餐饮
    if any(kw in lowered for kw in ("local food", "本地菜", "特色美食", "local cuisine", "当地特色")):
        cards.append(
            build_constraint_card(
                category="dietary",
                description="偏好本地特色餐饮",
                parameters={"cuisine_preference": "local"},
                is_hard=False,
                source="nature_language",
                priority=2,
                card_id=f"nl_{idx}",
            )
        )
        idx += 1

    # 预算相关自然语言（与 DSL 互补）
    budget_patterns = [
        (r"accommodation budget[:\s]+([\d.]+)", "accommodation", "住宿预算"),
        (r"dining budget[:\s]+([\d.]+)", "dining", "餐饮预算"),
        (r"budget[:\s]+([\d.]+)", "total", "总预算"),
        (r"预算[:\s]*([\d.]+)", "total", "总预算"),
    ]
    for pattern, budget_type, label in budget_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            amount = float(match.group(1))
            cards.append(
                build_constraint_card(
                    category="budget",
                    description=f"{label}约 {amount}（自然语言抽取）",
                    parameters={"budget_type": budget_type, "max_cost": amount},
                    is_hard=False,
                    source="nature_language",
                    priority=3,
                    card_id=f"nl_{idx}",
                )
            )
            idx += 1

    # 必去景点（must visit / 一定要去）
    must_visit = re.findall(
        r"(?:must visit|必去|一定要去|想去)\s*[：:]?\s*([A-Za-z\u4e00-\u9fff0-9\s\-]+?)(?:[,.;，。]|$)",
        text,
        re.IGNORECASE,
    )
    for poi_name in must_visit:
        name = poi_name.strip()
        if len(name) >= 2:
            cards.append(
                build_constraint_card(
                    category="attraction",
                    description=f"必去景点: {name}",
                    parameters={"must_visit_poi": name},
                    is_hard=True,
                    source="nature_language",
                    priority=4,
                    card_id=f"nl_{idx}",
                )
            )
            idx += 1

    return cards
