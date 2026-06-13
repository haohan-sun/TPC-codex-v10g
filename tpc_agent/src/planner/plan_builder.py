"""核心行程构建：约束驱动 + ChinaTravel WorldEnv。"""

from __future__ import annotations

from typing import Any

from src.data_layer.chinatravel_bridge import infer_lang
from src.data_layer.schema import CandidatePool, Constraints, POICandidate
from src.data_layer.world_env_client import SandboxClient, get_sandbox
from src.planner.constraint_profile import (
    PlanningConstraints,
    extract_planning_constraints,
    max_meal_price,
)
from src.planner.plan_utils import (
    add_minutes,
    is_valid_time_format,
    make_activity,
    make_intercity_activity,
    max_time,
    normalize_transports,
    time_to_minutes,
)


def _poi_price(poi: POICandidate | None, default: float = 0.0) -> float:
    if poi is None:
        return default
    meta = poi.metadata or {}
    for key in ("price", "cost", "ticket_price", "Price"):
        if meta.get(key) not in (None, ""):
            try:
                return float(meta[key])
            except (TypeError, ValueError):
                pass
    return default


def _records_to_candidates(records: list[dict[str, Any]]) -> list[POICandidate]:
    out: list[POICandidate] = []
    for r in records:
        if not r.get("name"):
            continue
        out.append(POICandidate(
            poi_id=str(r.get("id", r.get("name"))),
            name=str(r.get("name")),
            metadata=r,
        ))
    return out


def _ensure_candidates(
    sandbox: SandboxClient,
    target_city: str,
    candidates: CandidatePool,
) -> tuple[list[POICandidate], list[POICandidate], list[POICandidate]]:
    pois = list(candidates.pois or [])
    hotels = list(candidates.hotels or [])
    restaurants = list(candidates.restaurants or [])

    if not pois:
        pois = _records_to_candidates(sandbox.list_attractions(target_city, limit=30))
    if not hotels:
        hotels = _records_to_candidates(sandbox.list_hotels(target_city, limit=20))
    if not hotels:
        hotels = [POICandidate(
            poi_id="hotel_default",
            name=f"{target_city} Central Hotel",
            metadata={"price": 300.0},
        )]
    if not restaurants:
        restaurants = _records_to_candidates(sandbox.list_restaurants(target_city, limit=30))
    return pois, hotels, restaurants


def _select_hotel(
    sandbox: SandboxClient,
    pc: PlanningConstraints,
    hotels: list[POICandidate],
) -> POICandidate | None:
    if not hotels:
        return None

    pool = hotels
    if pc.hotel_near_anchor and pc.hotel_max_distance_km:
        nearby = sandbox.hotels_nearby(
            pc.target_city,
            pc.hotel_near_anchor,
            topk=30,
            max_dist_km=pc.hotel_max_distance_km + 0.01,
        )
        if nearby:
            pool = _records_to_candidates(nearby)

    if pc.required_hotel_type:
        filtered = [
            h for h in pool
            if pc.required_hotel_type in str((h.metadata or {}).get("featurehoteltype", ""))
            or pc.required_hotel_type in str((h.metadata or {}).get("featureHotelType", ""))
        ]
        if filtered:
            pool = filtered

    rooms = max(1, (pc.people + 1) // 2)
    nights = max(1, pc.days - 1)
    if pc.accommodation_budget is not None:
        affordable = [h for h in pool if _poi_price(h, 9999) * rooms * nights <= pc.accommodation_budget]
        if affordable:
            pool = affordable

    pool = sorted(pool, key=lambda h: _poi_price(h, 9999))
    return pool[0] if pool else hotels[0]


def _select_restaurants(
    pc: PlanningConstraints,
    restaurants: list[POICandidate],
) -> tuple[POICandidate | None, POICandidate | None, POICandidate | None]:
    """返回 (breakfast, lunch, dinner) 候选，三餐不重复。"""
    if not restaurants:
        placeholder = POICandidate(
            poi_id="meal_default",
            name=f"{pc.target_city} Local Restaurant",
            metadata={"price": 30.0},
        )
        return placeholder, placeholder, placeholder

    cap = max_meal_price(pc)
    affordable = restaurants
    if cap is not None:
        affordable = [r for r in restaurants if _poi_price(r, 999) <= cap]
        if not affordable:
            affordable = sorted(restaurants, key=lambda r: _poi_price(r))[:5]

    affordable = sorted(affordable, key=lambda r: _poi_price(r))
    # 选三个不同餐厅（breakfast / lunch / dinner 不重复）
    if len(affordable) >= 3:
        breakfast_r = affordable[0]
        lunch_r = affordable[1]
        dinner_r = affordable[2]
    elif len(affordable) == 2:
        breakfast_r = affordable[0]
        lunch_r = affordable[1]
        dinner_r = affordable[0]
    else:
        breakfast_r = lunch_r = dinner_r = affordable[0]
    return breakfast_r, lunch_r, dinner_r


def _pick_pois_per_day(
    pois: list[POICandidate],
    num_days: int,
    pc: PlanningConstraints,
    policy: str,
    pace_weight: float,
) -> list[list[POICandidate]]:
    """Rolling task allocation: choose each day from current remaining state."""
    if not pois or num_days <= 0:
        return [[] for _ in range(max(num_days, 1))]

    remaining = [p for p in pois if _poi_allowed(p, pc)]
    must = [p for p in remaining if _is_must_poi(p, pc)]
    others = [p for p in remaining if p not in must]

    if policy == "budget":
        others.sort(key=lambda p: (_poi_price(p, 0.0), -p.score))
    else:
        others.sort(key=lambda p: -p.score)

    ordered_remaining = _dedupe_candidates(must + others)
    days: list[list[POICandidate]] = []
    current_anchor: POICandidate | None = None

    for day_idx in range(num_days):
        capacity = _daily_capacity(policy, pace_weight, pc, is_final_day=day_idx == num_days - 1)
        day_items: list[POICandidate] = []

        while ordered_remaining and len(day_items) < capacity:
            if policy == "low_transport":
                idx = _nearest_candidate_index(current_anchor or (day_items[-1] if day_items else None), ordered_remaining)
            elif policy == "must_visit_first":
                idx = 0
            else:
                idx = _best_candidate_index(ordered_remaining, policy)
            chosen = ordered_remaining.pop(idx)
            day_items.append(chosen)
            current_anchor = chosen

        days.append(day_items)

    return days


def _daily_capacity(policy: str, pace_weight: float, pc: PlanningConstraints, *, is_final_day: bool) -> int:
    if pc.max_pois_per_day:
        cap = pc.max_pois_per_day
    elif policy == "safe" or pc.pace == "relaxed" or pace_weight < 0.4:
        cap = 2
    elif policy == "preference" or pc.pace == "intensive" or pace_weight > 0.6:
        cap = 4
    else:
        cap = 3
    if policy == "budget":
        cap = min(cap, 2)
    if is_final_day:
        cap = max(1, cap - 1)
    return max(1, cap)


def _dedupe_candidates(items: list[POICandidate]) -> list[POICandidate]:
    seen: set[str] = set()
    out: list[POICandidate] = []
    for item in items:
        key = item.poi_id or item.name
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _poi_allowed(poi: POICandidate, pc: PlanningConstraints) -> bool:
    name_l = poi.name.lower()
    ptype = str((poi.metadata or {}).get("type", "")).lower()
    if any(f.lower() in name_l for f in pc.forbidden_pois):
        return False
    return not any(f.lower() in ptype or f.lower() in name_l for f in pc.forbidden_attraction_types)


def _is_must_poi(poi: POICandidate, pc: PlanningConstraints) -> bool:
    name_l = poi.name.lower()
    pid_l = poi.poi_id.lower()
    ptype = str((poi.metadata or {}).get("type", "")).lower()
    if any(m.lower() in name_l or m.lower() == pid_l for m in pc.must_visit):
        return True
    return any(t.lower() in ptype or t.lower() in name_l for t in pc.must_visit_types)


def _best_candidate_index(candidates: list[POICandidate], policy: str) -> int:
    if policy == "budget":
        return min(range(len(candidates)), key=lambda i: (_poi_price(candidates[i], 0.0), -candidates[i].score))
    return max(range(len(candidates)), key=lambda i: candidates[i].score)


def _nearest_candidate_index(anchor: POICandidate | None, candidates: list[POICandidate]) -> int:
    if anchor is None:
        return 0
    return min(range(len(candidates)), key=lambda i: _candidate_distance(anchor, candidates[i]))


def _candidate_distance(a: POICandidate, b: POICandidate) -> float:
    ca, cb = _coords(a.metadata or {}), _coords(b.metadata or {})
    if ca and cb:
        r = 6371.0
        import math

        phi1, phi2 = math.radians(ca[0]), math.radians(cb[0])
        dphi = math.radians(cb[0] - ca[0])
        dlambda = math.radians(cb[1] - ca[1])
        x = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        return 2 * r * math.asin(math.sqrt(x))
    if a.region and b.region and a.region == b.region:
        return 0.5
    return 5.0


def _coords(rec: dict[str, Any]) -> tuple[float, float] | None:
    try:
        if "latitude" in rec and "longitude" in rec:
            return float(rec["latitude"]), float(rec["longitude"])
        if "lat" in rec and "lon" in rec:
            return float(rec["lat"]), float(rec["lon"])
        if "lat" in rec and "lng" in rec:
            return float(rec["lat"]), float(rec["lng"])
    except (TypeError, ValueError):
        return None
    return None


def _intercity_end_position(row: dict[str, Any], target_city: str) -> str:
    end = row.get("To") or row.get("end") or target_city
    if row.get("type") == "airplane":
        return str(row.get("To") or row.get("end") or f"{target_city} Airport")
    if row.get("type") == "train":
        return str(row.get("To") or row.get("end") or f"{target_city} Station")
    return str(end)


def _goto(
    sandbox: SandboxClient,
    pc: PlanningConstraints,
    city: str,
    start: str,
    end: str,
    start_time: str,
    *,
    use_taxi: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    if not start or not end:
        return [], start_time
    mode = "taxi" if use_taxi else "metro"
    if not pc.prefer_metro and pc.prefer_taxi_for_hotel:
        mode = "taxi"
    segments = sandbox.goto(
        city, start, end, start_time, mode,
        people=pc.people,
        taxi_cars=pc.taxi_cars,
    )
    if not segments and mode == "metro":
        segments = sandbox.goto(
            city, start, end, start_time, "taxi",
            people=pc.people,
            taxi_cars=pc.taxi_cars,
        )
    end_time = segments[-1]["end_time"] if segments else start_time
    return normalize_transports(segments, pc.people, pc.taxi_cars), end_time


def _append_meal(
    activities: list[dict],
    meal_type: str,
    restaurant: POICandidate | None,
    sandbox: SandboxClient,
    pc: PlanningConstraints,
    pos: str,
    current_time: str,
    fallback_name: str,
) -> tuple[str, str]:
    name = restaurant.name if restaurant else fallback_name
    price = _poi_price(restaurant, 35.0 if meal_type == "breakfast" else 50.0)
    duration = 45 if meal_type == "breakfast" else 60
    if restaurant and not sandbox.is_restaurant_open(pc.target_city, name, current_time):
        meal_open_hint = {"breakfast": "07:30", "lunch": "11:30", "dinner": "17:30"}
        current_time = max_time(current_time, meal_open_hint.get(meal_type, "11:30"))

    try:
        transports, arrive = _goto(sandbox, pc, pc.target_city, pos, name, current_time)
        t_start = transports[0]["start_time"] if transports else current_time
        t_end = add_minutes(arrive, duration)
        activities.append(make_activity(
            meal_type, t_start, t_end,
            price * pc.people, price, transports,
            position=name, tickets=pc.people,
        ))
        next_time = add_minutes(t_end, 10)
        return name, next_time
    except RuntimeError:
        # 时间溢出：跳过此餐
        return pos, current_time


def build_day_activities(
    day_index: int,
    num_days: int,
    day_pois: list[POICandidate],
    hotel: POICandidate | None,
    meals: tuple[POICandidate | None, POICandidate | None, POICandidate | None],
    pc: PlanningConstraints,
    sandbox: SandboxClient,
    *,
    current_time: str = "09:00",
    prev_position: str = "",
    skip_breakfast: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    """构建单日 activity（餐饮/景点/住宿），满足票务与交通约束。"""
    target = pc.target_city
    activities: list[dict[str, Any]] = []
    pos = prev_position or (hotel.name if hotel else "")
    breakfast_r, lunch_r, dinner_r = meals

    if not skip_breakfast:
        try:
            pos, current_time = _append_meal(
                activities, "breakfast", breakfast_r, sandbox, pc, pos, current_time,
                f"{target} Breakfast Spot",
            )
        except RuntimeError:
            pass  # 早餐排不下，继续
    elif pos and time_to_minutes(current_time) < time_to_minutes("11:00"):
        current_time = "11:00"

    if not day_pois:
        try:
            pos, current_time = _append_meal(
                activities, "lunch", lunch_r, sandbox, pc, pos, current_time,
                f"{target} Lunch Spot",
            )
        except RuntimeError:
            pass

    skipped_pois = 0
    for i, poi in enumerate(day_pois):
        visit_min = 90
        meta = poi.metadata or {}
        if meta.get("recommendmintime"):
            try:
                visit_min = max(45, int(float(meta["recommendmintime"]) * 60))
            except (TypeError, ValueError):
                pass

        # 时间预算检查：估算本景点是否会溢出
        try:
            _ = add_minutes(current_time, 30 + visit_min + 15)  # ballpark check
        except RuntimeError:
            skipped_pois += 1
            continue  # 跳过此 POI，不强行塞入

        if not sandbox.is_attraction_open(target, poi.name, current_time):
            current_time = max_time(current_time, "09:30")

        try:
            transports, arrive = _goto(sandbox, pc, target, pos, poi.name, current_time)
            t_start = transports[0]["start_time"] if transports else current_time
            t_end = add_minutes(arrive, visit_min)
            price = _poi_price(poi, 0.0)
            activities.append(make_activity(
                "attraction", t_start, t_end,
                price * pc.people, price, transports,
                position=poi.name, tickets=pc.activity_tickets or pc.people,
            ))
            pos = poi.name
            current_time = add_minutes(t_end, pc.buffer_minutes)
        except RuntimeError:
            skipped_pois += 1
            continue  # 时间溢出，跳过此 POI

        if i == 0:
            try:
                pos, current_time = _append_meal(
                    activities, "lunch", lunch_r, sandbox, pc, pos, current_time,
                    f"{target} Lunch Spot",
                )
            except RuntimeError:
                pass  # 午餐排不下就算了

    try:
        pos, current_time = _append_meal(
            activities, "dinner", dinner_r, sandbox, pc, pos,
            max_time(current_time, "17:30"),
            f"{target} Dinner Spot",
        )
    except RuntimeError:
        pass  # 晚餐排不下，跳过

    if day_index < num_days and hotel:
        try:
            at0 = max_time(current_time, "20:00")
            hp = _poi_price(hotel, 300.0)
            transports, arrive = _goto(
                sandbox, pc, target, pos, hotel.name, at0, use_taxi=True,
            )
            at1 = add_minutes(arrive, 60)
            if time_to_minutes(at1) <= time_to_minutes(at0):
                at1 = add_minutes(at0, 120)
            rooms = max(1, (pc.people + 1) // 2)
            activities.append(make_activity(
                "accommodation", at0, at1,
                hp * rooms, hp, transports,
                position=hotel.name, tickets=pc.people,
                extra={"rooms": rooms, "room_type": 1},
            ))
            pos = hotel.name
        except RuntimeError:
            pass  # 住宿排不下，跳过

    return activities, pos


def build_full_plan_dict(
    constraints: Constraints,
    candidates: CandidatePool,
    preferences,
    policy: str = "safe",
) -> dict[str, Any]:
    """构建完整官方 plan 字典。"""
    pc = extract_planning_constraints(constraints)
    lang = infer_lang(pc.target_city or pc.start_city)
    sandbox = get_sandbox(lang)

    pois, hotels, restaurants = _ensure_candidates(sandbox, pc.target_city, candidates)
    hotel = _select_hotel(sandbox, pc, hotels)
    meals = _select_restaurants(pc, restaurants)

    pace = getattr(preferences, "pace_weight", 0.5)
    poi_by_day = _pick_pois_per_day(pois, pc.days, pc, policy, pace)

    itinerary: list[dict] = []
    prev_pos = hotel.name if hotel else ""
    hotel_anchor = prev_pos
    last_day_end_time = "18:00"  # 追踪最后一天用于返程交通

    for day_idx in range(pc.days):
        day_num = day_idx + 1
        acts: list[dict] = []
        # 每天重置开始时间，防止多日时间累积溢出
        current_time = "09:00"
        skip_breakfast = False

        if day_idx == 0:
            go = sandbox.select_intercity(
                pc.start_city, pc.target_city, pc.intercity_mode, "06:00",
            )
            if go:
                acts.append(make_intercity_activity(go, pc.people))
                prev_pos = _intercity_end_position(go, pc.target_city)
                # 城际到达可能跨午夜，allow_overflow=True
                raw_end = go.get("EndTime") or go.get("end_time") or "10:30"
                try:
                    current_time = add_minutes(raw_end, 30, allow_overflow=True)
                    # 如果溢出（>23:59），钳制到 09:00 开始下一天
                    if time_to_minutes(current_time) >= 24 * 60:
                        current_time = "09:00"
                except RuntimeError:
                    current_time = "09:00"
                skip_breakfast = time_to_minutes(current_time) >= time_to_minutes("10:00")
        else:
            # Day 2+ 从酒店出发，时间重置为 09:00
            prev_pos = hotel_anchor or prev_pos
            current_time = "09:00"

        day_acts, prev_pos = build_day_activities(
            day_num, pc.days, poi_by_day[day_idx], hotel, meals, pc, sandbox,
            current_time=current_time,
            prev_position=prev_pos,
            skip_breakfast=skip_breakfast,
        )
        acts.extend(day_acts)

        # 记录每天最后一个活动时间（用于最后一天返程）
        for act in reversed(day_acts):
            if act.get("end_time"):
                last_day_end_time = act["end_time"]
                break

        if day_idx == pc.days - 1:
            back_time = max_time(last_day_end_time, "18:00")
            # 先加从最后位置到车站/机场的交通
            station_name = f"{pc.target_city} Station"
            if pc.intercity_mode == "airplane":
                station_name = f"{pc.target_city} Airport"
            if prev_pos and prev_pos != station_name:
                try:
                    station_transports, station_arrive = _goto(
                        sandbox, pc, pc.target_city, prev_pos, station_name, back_time,
                    )
                    if station_transports:
                        seg_start = station_transports[0]["start_time"]
                        seg_end = station_transports[-1]["end_time"]
                        # 从 prev_pos 到车站的 transport（不作为独立 activity，作为返程前的衔接）
                        back_time = max_time(seg_end, back_time)
                except RuntimeError:
                    pass

            # 尝试城际返程，时间溢出则换更早车次
            back = None
            for try_earliest in (back_time, "18:00", "16:00", "14:00"):
                try:
                    candidate = sandbox.select_intercity(
                        pc.target_city, pc.start_city, pc.intercity_mode, try_earliest,
                    )
                    if candidate:
                        back = candidate
                        break
                except Exception:
                    continue
            if back:
                try:
                    acts.append(make_intercity_activity(back, pc.people, is_return=True))
                except (ValueError, RuntimeError):
                    pass  # 缺真实 ID 或时间不可行，跳过返程

        # 按 start_time 排序确保时序正确
        acts.sort(key=lambda a: (time_to_minutes(a.get("start_time", "00:00")), a.get("type") in ("airplane", "train")))
        itinerary.append({"day": day_num, "activities": acts})

    # 写出前校验时间格式，发现违规直接 fail fast
    for day_entry in itinerary:
        for act in day_entry.get("activities", []):
            for field in ("start_time", "end_time"):
                t = act.get(field, "")
                if t and not is_valid_time_format(t):
                    raise RuntimeError(
                        f"时间格式违规: day={day_entry.get('day')} type={act.get('type')} "
                        f"{field}={t!r}（非 HH:MM 两位小时）"
                    )
            for seg in act.get("transports", []):
                for field in ("start_time", "end_time"):
                    t = seg.get(field, "")
                    if t and not is_valid_time_format(t):
                        raise RuntimeError(
                            f"transport 时间格式违规: day={day_entry.get('day')} "
                            f"type={act.get('type')} {field}={t!r}"
                        )

    return {
        "people_number": pc.people,
        "start_city": pc.start_city,
        "target_city": pc.target_city,
        "itinerary": itinerary,
        "_planning_constraints": pc,
    }
