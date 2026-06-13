"""Offline natural-language constraint extraction.

The competition mode cannot rely on external APIs or oracle hard_logic_py, so this
module uses a local dictionary/rule parser.  It intentionally extracts explicit
constraints from common ChinaTravel query phrasings and leaves ambiguous items as
soft preferences where possible.

Dictionaries are maintained in src/constraints/lexicons/.
"""

from __future__ import annotations

import re

from src.constraints.constraint_card import build_constraint_card
from src.constraints.lexicons.attraction_types import (
    ATTRACTION_TYPE_EN,
    FORBIDDEN_MARKERS_EN,
    FORBIDDEN_MARKERS_ZH,
    MUST_VISIT_MARKERS_EN,
    MUST_VISIT_MARKERS_ZH,
)
from src.constraints.lexicons.budget_phrases import (
    DINING_BUDGET_EN,
    TOTAL_BUDGET_EN,
)
from src.constraints.lexicons.cuisine_phrases import CUISINE_MAP_EN, CUISINE_MAP_ZH
from src.constraints.lexicons.hotel_phrases import (
    HOTEL_DISTANCE_EN,
    HOTEL_DISTANCE_ZH,
    HOTEL_FEATURE_EN,
    HOTEL_FEATURE_ZH,
    HOTEL_NEAR_MARKERS_EN,
    HOTEL_NEAR_MARKERS_ZH,
)
from src.constraints.lexicons.pace_phrases import (
    INTENSIVE_PACE_EN,
    INTENSIVE_PACE_ZH,
    RELAXED_PACE_EN,
    RELAXED_PACE_ZH,
)
from src.constraints.lexicons.transport_phrases import (
    AIRPLANE_PREFERENCE_EN,
    AIRPLANE_PREFERENCE_ZH,
    METRO_PREFERENCE_EN,
    METRO_PREFERENCE_ZH,
    TAXI_PREFERENCE_EN,
    TAXI_PREFERENCE_ZH,
    TRAIN_PREFERENCE_EN,
    TRAIN_PREFERENCE_ZH,
)
from src.data_layer.schema import ConstraintCard


AMOUNT_RE = r"([0-9]+(?:\.[0-9]+)?)"

# 合并中英文词汇表
RELAXED_PACE = RELAXED_PACE_EN + RELAXED_PACE_ZH
INTENSIVE_PACE = INTENSIVE_PACE_EN + INTENSIVE_PACE_ZH
FORBIDDEN_MARKERS = FORBIDDEN_MARKERS_EN + FORBIDDEN_MARKERS_ZH
MUST_VISIT_MARKERS = MUST_VISIT_MARKERS_EN + MUST_VISIT_MARKERS_ZH
CUISINE_TERMS = {**CUISINE_MAP_EN, **CUISINE_MAP_ZH}
HOTEL_FEATURES = {**HOTEL_FEATURE_EN, **HOTEL_FEATURE_ZH}
TRAIN_PREFERENCE = TRAIN_PREFERENCE_EN + TRAIN_PREFERENCE_ZH
AIRPLANE_PREFERENCE = AIRPLANE_PREFERENCE_EN + AIRPLANE_PREFERENCE_ZH
METRO_PREFERENCE = METRO_PREFERENCE_EN + METRO_PREFERENCE_ZH
TAXI_PREFERENCE = TAXI_PREFERENCE_EN + TAXI_PREFERENCE_ZH

ATTRACTION_TYPE_TERMS = set(ATTRACTION_TYPE_EN)


def parse_nature_language(text: str, start_index: int = 0) -> list[ConstraintCard]:
    """Extract constraint cards from natural-language query text."""
    if not text or not text.strip():
        return []

    cards: list[ConstraintCard] = []
    idx = start_index
    lowered = text.lower()

    def add_card(**kwargs) -> None:
        nonlocal idx
        kwargs.setdefault("card_id", f"nl_{idx}")
        cards.append(build_constraint_card(**kwargs))
        idx += 1

    # Pace as energy/time budget.
    if _contains_any(lowered, *RELAXED_PACE):
        add_card(
            category="preference",
            description="Relaxed pace: fewer POIs, less travel, more buffer time",
            parameters={"pace": "relaxed", "max_pois_per_day": 2, "buffer_minutes": 30},
            is_hard=False,
            source="nature_language",
            priority=2,
        )

    if _contains_any(lowered, *INTENSIVE_PACE):
        add_card(
            category="preference",
            description="Intensive pace: visit more POIs per day when feasible",
            parameters={"pace": "intensive", "max_pois_per_day": 4, "buffer_minutes": 10},
            is_hard=False,
            source="nature_language",
            priority=2,
        )

    # Budget constraints.
    budget_patterns = [
        (rf"(?:dining|food|meal|restaurant)\s+budget\s*(?:is|below|under|<=|less than|no more than|:)?\s*{AMOUNT_RE}", "dining", "Dining budget"),
        (rf"budget\s+for\s+(?:dining|food|meal|restaurant)s?\s*(?:is|below|under|<=|less than|no more than|:)?\s*{AMOUNT_RE}", "dining", "Dining budget"),
        (rf"(?:accommodation|hotel|lodging)\s+budget\s*(?:is|below|under|<=|less than|no more than|:)?\s*{AMOUNT_RE}", "accommodation", "Accommodation budget"),
        (rf"(?:total|overall|travel)\s+budget\s*(?:is|below|under|<=|less than|no more than|:)?\s*{AMOUNT_RE}", "total", "Total budget"),
        (rf"预算[:：\s]*(?:不超过|低于|小于)?\s*{AMOUNT_RE}", "total", "Total budget"),
    ]
    for pattern, budget_type, label in budget_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            amount = float(match.group(1))
            add_card(
                category="budget",
                description=f"{label} <= {amount}",
                parameters={"budget_type": budget_type, "max_cost": amount},
                is_hard=True,
                source="nature_language",
                priority=4,
            )

    # Hotel/accommodation spatial anchor (English)
    hotel_distance_patterns_en = [
        rf"(?:accommodation|hotel|lodging)\s+(?:should\s+be\s+)?(?:within|less than|no more than|under)\s*{AMOUNT_RE}\s*(?:km|kilometers?)\s*(?:of|from|near)\s+([^.;,]+)",
        rf"(?:stay|hotel|accommodation)\s+(?:near|close to)\s+([^.;,]+)\s+(?:within|under|less than)\s*{AMOUNT_RE}\s*(?:km|kilometers?)",
    ]
    for pattern in hotel_distance_patterns_en:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            g = match.groups()
            if len(g) == 2 and _is_number(g[0]):
                _add_hotel_distance_card(add_card, float(g[0]), g[1].strip())
            elif len(g) == 2 and _is_number(g[1]):
                _add_hotel_distance_card(add_card, float(g[1]), g[0].strip())

    # 中文酒店距离：独立处理，避免 regex 编码问题
    _parse_chinese_hotel_distance(text, add_card)

    # Required hotel features.
    for phrase, feature_type in HOTEL_FEATURES.items():
        if phrase in lowered:
            add_card(
                category="accommodation",
                description=f"Accommodation must include {feature_type}",
                parameters={"required_type": feature_type},
                is_hard=True,
                source="nature_language",
                priority=4,
            )
            break  # 只匹配优先级最高的一个

    # Exact hotel names. These must be grounded to database names later.
    for name in _extract_required_hotel_names(text):
        add_card(
            category="accommodation",
            description=f"Required hotel name: {name}",
            parameters={"required_name": name},
            is_hard=True,
            source="nature_language",
            priority=5,
        )

    # Forbidden attractions/types before positive extraction.
    for phrase in _extract_forbidden_visit_phrases(text):
        _add_attraction_phrase_card(add_card, phrase, forbidden=True)

    # Positive must-visit or type requirements.
    for phrase in _extract_positive_visit_phrases(text):
        if _phrase_was_forbidden(text, phrase):
            continue
        _add_attraction_phrase_card(add_card, phrase, forbidden=False)

    # Cuisine and restaurant preferences.
    for term, canonical in CUISINE_TERMS.items():
        if term in lowered:
            add_card(
                category="dietary",
                description=f"Restaurant/cuisine preference: {canonical}",
                parameters={"cuisine_preference": canonical},
                is_hard=False,
                source="nature_language",
                priority=2,
            )

    # Exact restaurant names. For hard logic, activity_position must match them.
    for name in _extract_required_restaurant_names(text):
        add_card(
            category="dietary",
            description=f"Required restaurant name: {name}",
            parameters={"restaurant_name": name},
            is_hard=True,
            source="nature_language",
            priority=5,
        )

    # --- Free / no-cost constraints ---
    if _contains_any(lowered, "free", "no cost", "free of charge", "free admission",
                     "no admission", "free ticket", "no ticket cost",
                     "attractions are free", "free entry"):
        add_card(
            category="budget",
            description="Free attractions required (no admission cost)",
            parameters={"budget_type": "free_attraction", "max_cost": 0},
            is_hard=True,
            source="nature_language",
            priority=5,
        )
    if _contains_any(lowered, "free transport", "free intercity", "free train",
                     "free flight", "free transportation", "free airplane",
                     "no transport cost", "transportation is free"):
        add_card(
            category="budget",
            description="Free intercity transport required",
            parameters={"budget_type": "free_intercity", "max_cost": 0},
            is_hard=True,
            source="nature_language",
            priority=5,
        )

    # --- Low-budget / cheap / economical ---
    if _contains_any(lowered, "low-budget", "low budget", "tight budget",
                     "cheap", "economical", "budget-friendly", "on a budget",
                     "affordable", "save money", "cost-effective"):
        add_card(
            category="budget",
            description="Budget-conscious trip (prefer low-cost options)",
            parameters={"budget_type": "total", "max_cost": 5000},
            is_hard=False,
            source="nature_language",
            priority=3,
        )

    # --- Visit <POI> patterns (simplified: direct must_visit extraction) ---
    # "visit X, Y, and Z" / "go to X" / "see X"
    visit_end = _visit_clause_end_pattern()
    visit_patterns = [
        rf"\bvisit\s+(.+?){visit_end}",
        rf"\bgo\s+to\s+(.+?){visit_end}",
        rf"\bsee\s+(.+?){visit_end}",
        r"去\s*([^。]+?)(?:[。，]|$)",
    ]
    for pattern in visit_patterns:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            phrase = m.group(1).strip()
            for item in _split_visit_phrase(phrase):
                if len(item) >= 3 and not _looks_like_type(item) and item.lower() not in (
                    "the city", "downtown", "old town", "new town", "all", "them", "it"
                ):
                    add_card(
                        category="attraction",
                        description=f"Must visit: {item}",
                        parameters={"must_visit_poi": item},
                        is_hard=True,
                        source="nature_language",
                        priority=5,
                    )

    # Transport requirements/preferences.
    if _contains_any(lowered, *TRAIN_PREFERENCE):
        add_card(
            category="transport",
            description="Intercity transport should use train",
            parameters={"intercity_mode": "train"},
            is_hard=True,
            source="nature_language",
            priority=4,
        )
    if _contains_any(lowered, *AIRPLANE_PREFERENCE):
        add_card(
            category="transport",
            description="Intercity transport should use airplane",
            parameters={"intercity_mode": "airplane"},
            is_hard=True,
            source="nature_language",
            priority=4,
        )
    if _contains_any(lowered, *METRO_PREFERENCE):
        add_card(
            category="transport",
            description="Prefer metro for inner-city transport",
            parameters={"innercity_mode": "metro"},
            is_hard=False,
            source="nature_language",
            priority=2,
        )
    if _contains_any(lowered, *TAXI_PREFERENCE):
        add_card(
            category="transport",
            description="Prefer taxi for inner-city transport",
            parameters={"innercity_mode": "taxi"},
            is_hard=False,
            source="nature_language",
            priority=2,
        )

    return cards


def _contains_any(text: str, *keywords: str) -> bool:
    return any(k.lower() in text for k in keywords)


def _is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _clean_entity(value: str) -> str:
    value = re.sub(r"\b(?:with|during|for)\b.*$", "", value.strip(), flags=re.IGNORECASE)
    return value.strip(" ,.;:，。；：")


def _looks_like_type(phrase: str) -> bool:
    p = phrase.lower().strip(" ,.;:")
    p = re.sub(r"^(?:the|a|an)\s+", "", p)
    if p in ATTRACTION_TYPE_TERMS:
        return True
    if p.endswith("s") and p[:-1] in ATTRACTION_TYPE_TERMS:
        return True
    return False


def _split_visit_phrase(phrase: str) -> list[str]:
    phrase = _clean_entity(phrase)
    phrase = re.sub(r"^(?:the|a|an)\s+", "", phrase, flags=re.IGNORECASE)
    parts = re.split(r"\s+(?:and|or)\s+|[,，；;]\s*", phrase)
    cleaned: list[str] = []
    for part in parts:
        item = _clean_entity(part)
        item = re.sub(r"^(?:and|or)\s+", "", item, flags=re.IGNORECASE)
        if len(item) >= 2:
            cleaned.append(item)
    return cleaned


def _extract_required_hotel_names(text: str) -> list[str]:
    patterns = [
        r"(?:one\s+of\s+(?:the\s+)?following\s+hotels?|following\s+hotels?|these\s+hotels?)\s*:\s*([^.;\n]+)",
        r"(?:hope|wish|want|prefer|would\s+like)\s+to\s+stay\s+at\s+([^.;\n]+)",
    ]
    return _extract_named_items(text, patterns, split_commas=False, kind="hotel")


def _extract_required_restaurant_names(text: str) -> list[str]:
    patterns = [
        r"(?:one\s+of\s+(?:these|the\s+following)\s+restaurants?|following\s+restaurants?|these\s+restaurants?)\s*:\s*([^.;\n]+)",
        r"(?:restaurants?)\s*:\s*([^.;\n]+)",
    ]
    return _extract_named_items(text, patterns, split_commas=True, kind="restaurant")


def _extract_named_items(
    text: str,
    patterns: list[str],
    *,
    split_commas: bool,
    kind: str,
) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            if _forbidden_context_before(text, match.start()):
                continue
            body = match.group(1).strip()
            for item in _split_named_list(body, split_commas=split_commas):
                if not _looks_like_named_entity(item, kind):
                    continue
                key = item.lower()
                if key in seen:
                    continue
                seen.add(key)
                names.append(item)
    return names


def _split_named_list(body: str, *, split_commas: bool) -> list[str]:
    body = re.sub(
        r"^\s*(?:one\s+of\s+)?(?:the\s+)?(?:following|these)\s+hotels?\s*:\s*",
        "",
        body,
        flags=re.IGNORECASE,
    )
    body = re.sub(r"^\s*(?:one\s+of\s+)?(?:the\s+)?(?:following|these)\s+", "", body, flags=re.IGNORECASE)
    body = body.strip()
    if split_commas:
        body = re.sub(r"\s+\band\b\s+", ", ", body, flags=re.IGNORECASE)
        raw_parts = re.split(r"\s+\bor\s+|[,;]\s*", body, flags=re.IGNORECASE)
    else:
        raw_parts = re.split(r"\s+\bor\s+|[;]\s*", body, flags=re.IGNORECASE)
    parts: list[str] = []
    for raw in raw_parts:
        item = re.sub(r"^\s*\d+\.\s*", "", raw.strip())
        item = re.sub(r"^(?:and|or)\s+", "", item, flags=re.IGNORECASE)
        item = _clean_entity(item)
        if item:
            parts.append(item)
    return parts


def _forbidden_context_before(text: str, index: int) -> bool:
    prefix = text[max(0, index - 64):index].lower()
    return any(token in prefix for token in (
        "do not", "don't", "not want", "not wish", "prefer not",
        "avoid", "exclude", "forbidden",
    ))


def _looks_like_named_entity(item: str, kind: str) -> bool:
    low = item.lower().strip()
    if len(low) < 3:
        return False
    bad_prefixes = (
        "a hotel", "hotel with", "hotel that", "a restaurant type",
        "restaurant type", "one of", "the following", "these ",
    )
    if low.startswith(bad_prefixes):
        return False
    if kind == "hotel" and low.startswith("a ") and "type hotel" in low:
        return False
    if kind == "hotel" and any(token in low for token in (" within ", " near ", " with ")):
        return False
    return True


def _extract_forbidden_visit_phrases(text: str) -> list[str]:
    patterns = [
        r"(?:do\s+not|don't|do\s+not\s+wish\s+to|do\s+not\s+want\s+to|not\s+to)\s+visit\s+([^.;]+)",
        r"(?:avoid|exclude|without)\s+([^.;]+)",
        r"不(?:想|要|希望)?去\s*([^。；;,.，]+)",
    ]
    phrases: list[str] = []
    for pattern in patterns:
        phrases.extend(m.group(1).strip() for m in re.finditer(pattern, text, re.IGNORECASE))
    return phrases


def _extract_positive_visit_phrases(text: str) -> list[str]:
    visit_end = _visit_clause_end_pattern()
    patterns = [
        rf"(?:must|need|want|would\s+like|wish|hope|plan)\s+to\s+visit\s+(.+?){visit_end}",
        r"(?:must|need|want)\s+visit\s+([^.;]+)",  # "Must visit X" 省略 to
        rf"(?:we\s+want\s+to\s+visit|requirements:\s*visit)\s+(.+?){visit_end}",
        r"(?:必须|一定|想|希望)去\s*([^。；;,.，]+)",
    ]
    phrases: list[str] = []
    for pattern in patterns:
        phrases.extend(m.group(1).strip() for m in re.finditer(pattern, text, re.IGNORECASE))
    return phrases


def _visit_clause_end_pattern() -> str:
    next_sentence = (
        "We|I|Do|Don't|The|This|Budget|Requirements?|Please|Accommodation|"
        "Hotel|Total|Inter-city|Intra-city|Prefer|Wish|Want|Hope"
    )
    return rf"(?=(?:\.\s+(?:{next_sentence})|\.\s*$|[;\n]|$))"


def _phrase_was_forbidden(text: str, phrase: str) -> bool:
    phrase_l = phrase.lower()
    text_l = text.lower()
    idx = text_l.find(phrase_l)
    if idx < 0:
        return False
    prefix = text_l[max(0, idx - 32):idx]
    return any(token in prefix for token in ("do not", "don't", "not ", "avoid", "exclude", "不想", "不要"))


def _add_attraction_phrase_card(add_card, phrase: str, *, forbidden: bool) -> None:
    for item in _split_visit_phrase(phrase):
        if _looks_like_type(item):
            param = "forbidden_attraction_type" if forbidden else "must_visit_type"
            add_card(
                category="attraction",
                description=("Forbidden" if forbidden else "Required") + f" attraction type: {item}",
                parameters={param: item},
                is_hard=True,
                source="nature_language",
                priority=5 if not forbidden else 4,
            )
        else:
            param = "forbidden_poi" if forbidden else "must_visit_poi"
            add_card(
                category="attraction",
                description=("Forbidden" if forbidden else "Must visit") + f" attraction: {item}",
                parameters={param: item},
                is_hard=True,
                source="nature_language",
                priority=5 if not forbidden else 4,
            )


def _add_hotel_distance_card(add_card, dist: float, anchor: str) -> None:
    """添加酒店距离约束卡片。"""
    if dist <= 0 or not anchor.strip():
        return
    add_card(
        category="spatial",
        description=f"Accommodation within {dist} km of {anchor.strip()}",
        parameters={
            "target": "accommodation",
            "anchor_poi": _clean_entity(anchor),
            "max_distance_km": dist,
        },
        is_hard=True,
        source="nature_language",
        priority=5,
    )


def _parse_chinese_hotel_distance(text: str, add_card) -> None:
    """中文酒店距离约束提取：住宿在X附近N公里以内。"""
    # 模式：住宿/酒店/旅馆 + 在/位于 + POI名 + 附近/周边 + 数字 + 公里/米 + 以内
    pattern = re.compile(
        r"(?:住宿|酒店|旅馆)\s*(?:在|位于)?\s*"
        r"([^0-9。；;,.，]{2,20}?)\s*"
        r"(?:附近|周边)?\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*"
        r"(?:公里|千米|km|米|m)\s*"
        r"(?:以内|之内|范围)?"
    )
    for m in pattern.finditer(text):
        anchor = m.group(1).strip()
        try:
            dist = float(m.group(2))
        except (TypeError, ValueError):
            continue
        if m.group(0).endswith(("米", "m")) and not m.group(0).endswith(("千米", "km")):
            dist = dist / 1000.0  # 米转公里
        if dist <= 0 or not anchor:
            continue
        add_card(
            category="spatial",
            description=f"Accommodation within {dist} km of {anchor}",
            parameters={
                "target": "accommodation",
                "anchor_poi": _clean_entity(anchor),
                "max_distance_km": dist,
            },
            is_hard=True,
            source="nature_language",
            priority=5,
        )
