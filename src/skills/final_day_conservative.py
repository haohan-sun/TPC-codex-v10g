"""技能：最后一天保守安排 — 减少景点、确保返程时间充裕。"""

from src.data_layer.schema import Plan
from src.planner.plan_utils import time_to_minutes


def final_day_conservative(plan: Plan, **kwargs) -> Plan:
    """最后一天最多保留 1 个景点，确保返程前有 ≥2h buffer。

    只缩减最后一天，不影响前几天的安排。
    """
    official = plan.metadata.get("official_plan") or {}
    itinerary = official.get("itinerary") or []
    if len(itinerary) < 2:
        return plan

    last_day = itinerary[-1]
    acts = last_day.get("activities") or []

    # 找到返程交通
    return_trip = None
    for a in acts:
        if a.get("type") in ("airplane", "train") and a.get("start"):
            return_trip = a
            break

    # 保留至多 1 个景点，其余删掉
    attractions = [a for a in acts if a.get("type") == "attraction"]
    others = [a for a in acts if a.get("type") != "attraction"]

    if len(attractions) > 1:
        # 保留 best（protected > cheapest）
        attractions.sort(key=lambda a: (
            not a.get("_protected", False),
            a.get("cost", 0),
        ))
        kept_attrs = attractions[:1]

        new_acts = []
        attr_idx = 0
        for a in acts:
            if a.get("type") == "attraction":
                if attr_idx < len(kept_attrs):
                    new_acts.append(kept_attrs[attr_idx])
                    attr_idx += 1
            else:
                new_acts.append(a)
        last_day["activities"] = new_acts

    # 确保返程前有 buffer
    if return_trip:
        depart = return_trip.get("start_time", "")
        if depart:
            depart_min = time_to_minutes(depart)
            for a in last_day["activities"]:
                end_min = time_to_minutes(a.get("end_time", "00:00"))
                if end_min > depart_min - 120 and a.get("type") != return_trip.get("type"):
                    # 冲突：删除此活动
                    last_day["activities"].remove(a)

    plan.metadata["official_plan"] = official
    plan.metadata["final_day_conservative_applied"] = True
    return plan
