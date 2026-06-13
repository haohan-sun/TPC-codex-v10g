"""技能：预算节省 — 替换高价餐厅/酒店为更便宜的候选。"""

from src.data_layer.schema import CandidatePool, Plan


def budget_saving(plan: Plan, candidates: CandidatePool | None = None, target_saving: float = 0.0, **kwargs) -> Plan:
    """在预算超支时替换为低价候选。

    优先级：换餐厅 → 换酒店 → taxi→walk
    """
    if candidates is None:
        return plan

    official = plan.metadata.get("official_plan") or {}
    itinerary = official.get("itinerary") or []

    budget_limit = plan.metadata.get("budget_limit")
    if budget_limit is None:
        return plan

    # 计算总花费
    total = sum(
        a.get("cost", 0)
        for day in itinerary
        for a in (day.get("activities") or [])
    )
    if total <= budget_limit:
        return plan

    cheap_restaurants = sorted(
        (candidates.restaurants or []),
        key=lambda r: float((r.metadata or {}).get("price", 999)),
    )
    cheap_hotels = sorted(
        (candidates.hotels or []),
        key=lambda h: float((h.metadata or {}).get("price", 999)),
    )

    # 1. 换餐厅
    for day in itinerary:
        for a in (day.get("activities") or []):
            if a.get("type") in ("breakfast", "lunch", "dinner"):
                current_price = a.get("price", 999)
                cheaper = [r for r in cheap_restaurants
                           if float((r.metadata or {}).get("price", 999)) < current_price]
                if cheaper:
                    r = cheaper[0]
                    a["position"] = r.name
                    new_price = float((r.metadata or {}).get("price", current_price))
                    a["price"] = new_price
                    a["cost"] = new_price

    # 2. 换酒店
    for day in itinerary:
        for a in (day.get("activities") or []):
            if a.get("type") == "accommodation":
                current_price = a.get("price", 999)
                cheaper = [h for h in cheap_hotels
                           if float((h.metadata or {}).get("price", 999)) < current_price]
                if cheaper:
                    h = cheaper[0]
                    a["position"] = h.name
                    new_price = float((h.metadata or {}).get("price", current_price))
                    a["price"] = new_price
                    a["cost"] = new_price * a.get("rooms", 1)

    # 3. taxi → walk (仅非住宿、非车站交通)
    for day in itinerary:
        for a in (day.get("activities") or []):
            for seg in (a.get("transports") or []):
                if seg.get("mode") == "taxi":
                    seg["mode"] = "walk"
                    seg["cost"] = 0.0
                    seg["price"] = 0.0

    plan.metadata["official_plan"] = official
    plan.metadata["budget_saving_applied"] = True
    return plan
