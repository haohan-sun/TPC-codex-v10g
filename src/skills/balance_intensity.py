"""技能：平衡行程强度 — 按 pace 调整每日景点数。"""

from src.data_layer.schema import Plan


def balance_intensity(plan: Plan, pace_weight: float = 0.5, **kwargs) -> Plan:
    """根据 pace 增减每日景点。

    pace < 0.4: relaxed → 每天 ≤2 POI
    pace > 0.6: intensive → 每天 ≤4 POI
    默认: moderate → 每天 ≤3 POI

    只调整数量，按 score/price 排序后保留 top-N。
    """
    official = plan.metadata.get("official_plan") or {}
    itinerary = official.get("itinerary") or []

    if pace_weight < 0.4:
        max_per_day = 2
    elif pace_weight > 0.6:
        max_per_day = 4
    else:
        max_per_day = 3

    for day in itinerary:
        acts = day.get("activities") or []
        # 保留非景点活动
        attractions = [a for a in acts if a.get("type") == "attraction"]
        others = [a for a in acts if a.get("type") != "attraction"]

        if len(attractions) > max_per_day:
            # 保留 top-N（优先 protected，其次按 cost 低→高）
            attractions.sort(key=lambda a: (
                not a.get("_protected", False),  # protected first
                a.get("cost", 0),
            ))
            kept = attractions[:max_per_day]
            # 重建 activities 列表（non-attraction 位置保持在景点之间）
            new_acts = []
            attr_idx = 0
            for a in acts:
                if a.get("type") == "attraction":
                    if attr_idx < len(kept):
                        new_acts.append(kept[attr_idx])
                        attr_idx += 1
                else:
                    new_acts.append(a)
            day["activities"] = new_acts

    plan.metadata["official_plan"] = official
    plan.metadata["balance_intensity_applied"] = True
    return plan
