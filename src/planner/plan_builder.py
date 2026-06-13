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
from src.skills.choose_hotel_anchor import choose_hotel_anchor_candidate
from src.skills.cross_city_day_light_plan import cross_city_day_light_plan
from src.skills.insert_meals import select_meal_candidates
from src.skills.lock_must_visit import lock_must_visit_order


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


def _norm_text(value: str) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def _name_matches(candidate_name: str, requested_name: str) -> bool:
    cand_norm = _norm_text(candidate_name)
    req_norm = _norm_text(requested_name)
    if not cand_norm or not req_norm:
        return False
    if cand_norm == req_norm:
        return True
    return len(req_norm) >= 12 and req_norm in cand_norm


def _candidate_matches_name(candidate: POICandidate, names: list[str]) -> bool:
    cand_name = candidate.name or ""
    return any(_name_matches(cand_name, name) for name in names)


def _filter_candidates_by_names(candidates: list[POICandidate], names: list[str]) -> list[POICandidate]:
    if not names:
        return []
    matched: list[POICandidate] = []
    for name in names:
        exact = [c for c in candidates if _norm_text(c.name) == _norm_text(name)]
        if exact:
            matched.extend(exact)
        else:
            matched.extend(c for c in candidates if _candidate_matches_name(c, [name]))
    return _dedupe_candidates(matched)


def _records_to_candidates(records: list[dict[str, Any]]) -> list[POICandidate]:
    out: list[POICandidate] = []
    for r in records:
        name = r.get("name")
        if not name or not str(name).strip():
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
    pc: PlanningConstraints | None = None,
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

    if pc:
        if pc.must_visit:
            pois = _prepend_named_records(
                pois,
                sandbox.list_attractions(target_city, limit=5000),
                pc.must_visit,
            )
        if pc.required_hotel_names:
            hotels = _prepend_named_records(
                hotels,
                sandbox.list_hotels(target_city, limit=5000),
                pc.required_hotel_names,
            )
        if pc.required_restaurant_names:
            restaurants = _prepend_named_records(
                restaurants,
                sandbox.list_restaurants(target_city, limit=5000),
                pc.required_restaurant_names,
            )
        if pc.cuisine_preferences:
            restaurants = _prepend_records_by_predicate(
                restaurants,
                sandbox.list_restaurants(target_city, limit=5000),
                lambda r: any(_record_matches_restaurant_type(r, pref) for pref in pc.cuisine_preferences),
            )
    return pois, hotels, restaurants


def _prepend_named_records(
    existing: list[POICandidate],
    records: list[dict[str, Any]],
    names: list[str],
) -> list[POICandidate]:
    matches = _filter_candidates_by_names(_records_to_candidates(records), names)
    return _dedupe_candidates(matches + existing)


def _prepend_records_by_predicate(
    existing: list[POICandidate],
    records: list[dict[str, Any]],
    predicate,
) -> list[POICandidate]:
    matches = [c for c in _records_to_candidates(records) if predicate(c.metadata or {})]
    return _dedupe_candidates(matches + existing)


def _record_matches_restaurant_type(record: dict[str, Any], wanted: str) -> bool:
    haystack = " ".join(str(record.get(k, "")) for k in ("name", "cuisine", "type", "recommendedfood"))
    return _norm_text(wanted) in _norm_text(haystack)


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

    name_filtered = _filter_candidates_by_names(pool, pc.required_hotel_names)
    if not name_filtered:
        name_filtered = _filter_candidates_by_names(hotels, pc.required_hotel_names)
    if name_filtered:
        pool = name_filtered

    rooms = max(1, (pc.people + 1) // 2)
    nights = max(1, pc.days - 1)
    if pc.accommodation_budget is not None:
        affordable = [h for h in pool if _poi_price(h, 9999) * rooms * nights <= pc.accommodation_budget]
        if affordable:
            pool = affordable
        elif name_filtered:
            pool = name_filtered

    pool = sorted(pool, key=lambda h: _poi_price(h, 9999))
    skill_result = choose_hotel_anchor_candidate(
        pool or hotels,
        pc,
        policy="safe",
        sandbox=sandbox,
    )
    selected_id = skill_result.decision.get("hotel_id")
    if selected_id:
        for hotel in pool or hotels:
            if hotel.poi_id == selected_id:
                return hotel
    return pool[0] if pool else hotels[0]


def _fmt_minutes(total: int) -> str:
    total = max(0, min(total, 23 * 60 + 59))
    return f"{total // 60:02d}:{total % 60:02d}"


def _clipped_end_time(start: str, duration_min: int = 60) -> str | None:
    try:
        start_min = time_to_minutes(start)
    except Exception:
        return None
    end_min = min(start_min + duration_min, 23 * 60 + 59)
    if end_min <= start_min:
        return None
    return _fmt_minutes(end_min)


def _activity_terminal_position(act: dict[str, Any], target_city: str) -> str:
    atype = act.get("type", "")
    if atype in ("airplane", "train"):
        return _intercity_end_position(act, target_city)
    return str(act.get("position") or act.get("end") or "")


def _activity_terminal_time(act: dict[str, Any]) -> str:
    end_time = str(act.get("end_time") or "")
    if is_valid_time_format(end_time):
        return end_time
    return "18:00"


def _is_same_day_time(time_str: str) -> bool:
    try:
        return is_valid_time_format(time_str) and 0 <= time_to_minutes(time_str) < 24 * 60
    except Exception:
        return False


def _anchor_from_activities(
    activities: list[dict[str, Any]],
    target_city: str,
    fallback_pos: str,
) -> tuple[str, str] | None:
    last_pos = fallback_pos
    last_end = "18:00"
    for act in activities:
        start = str(act.get("start_time") or "")
        end = str(act.get("end_time") or "")
        if not _is_same_day_time(start) or not _is_same_day_time(end):
            return None
        if time_to_minutes(end) <= time_to_minutes(start):
            return None
        pos = _activity_terminal_position(act, target_city)
        if pos:
            last_pos = pos
        last_end = end
    if not last_pos:
        return None
    return last_pos, last_end


def _unique_hotels(hotels: list[POICandidate]) -> list[POICandidate]:
    seen: set[str] = set()
    unique: list[POICandidate] = []
    for hotel in hotels:
        if not hotel or not hotel.name:
            continue
        key = hotel.name.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(hotel)
    return unique


def _make_reachable_accommodation(
    sandbox: SandboxClient,
    pc: PlanningConstraints,
    start_pos: str,
    start_after: str,
    hotels: list[POICandidate],
) -> tuple[dict[str, Any] | None, POICandidate | None]:
    if not hotels:
        return None, None

    try:
        depart = max_time(add_minutes(start_after, 10), "20:00")
    except Exception:
        depart = max_time(start_after if is_valid_time_format(start_after) else "20:00", "20:00")

    rooms = max(1, (pc.people + 1) // 2)
    for hotel in hotels:
        try:
            if start_pos and start_pos != hotel.name:
                transports, arrive = _goto(
                    sandbox, pc, pc.target_city, start_pos, hotel.name, depart,
                    use_taxi=True,
                )
                if not transports:
                    continue
            else:
                transports, arrive = [], depart
            end_time = _clipped_end_time(arrive, 60)
            if not end_time:
                continue
            price = _poi_price(hotel, 300.0)
            meta = hotel.metadata or {}
            room_type = int(meta.get("numbed", meta.get("room_type", 1)))
            activity = make_activity(
                "accommodation", arrive, end_time,
                price * rooms, price, transports,
                position=hotel.name, tickets=pc.people,
                extra={"rooms": rooms, "room_type": room_type},
            )
            return activity, hotel
        except Exception:
            continue
    return None, None


def ensure_required_accommodations(
    official: dict[str, Any],
    candidates: CandidatePool | None = None,
) -> dict[str, Any]:
    """Ensure every overnight day has a real, reachable accommodation."""
    pc = official.get("_planning_constraints")
    if not pc or getattr(pc, "days", 1) <= 1:
        return official

    itinerary = official.get("itinerary") or []
    if len(itinerary) <= 1:
        return official

    sandbox = get_sandbox(infer_lang(pc.target_city or pc.start_city))
    base_hotels = list(getattr(candidates, "hotels", []) or []) if candidates else []
    try:
        base_hotels.extend(_records_to_candidates(sandbox.list_hotels(pc.target_city, limit=100)))
    except Exception:
        pass
    if not base_hotels:
        return official

    preferred = _select_hotel(sandbox, pc, base_hotels)
    hotel_pool = _unique_hotels(([preferred] if preferred else []) + base_hotels)

    for day in itinerary[:-1]:
        activities = day.get("activities") or []
        if any(a.get("type") == "accommodation" and a.get("position") for a in activities):
            continue

        fallback_pos = preferred.name if preferred else ""
        for keep_count in range(len(activities), -1, -1):
            prefix = activities[:keep_count]
            anchor = _anchor_from_activities(prefix, pc.target_city, fallback_pos)
            if not anchor:
                continue
            last_pos, last_end = anchor
            accommodation, selected_hotel = _make_reachable_accommodation(
                sandbox, pc, last_pos, last_end, hotel_pool,
            )
            if accommodation:
                day["activities"] = prefix + [accommodation]
                if selected_hotel:
                    hotel_pool = _unique_hotels([selected_hotel] + hotel_pool)
                break

    return official


# 跨天餐厅使用追踪（避免多天重复同一餐厅）
_used_restaurant_names: set = set()


def _reset_restaurant_tracker() -> None:
    """每次新 plan 开始时重置餐厅追踪。"""
    global _used_restaurant_names
    _used_restaurant_names = set()


def _select_restaurants(
    pc: PlanningConstraints,
    restaurants: list[POICandidate],
    day_index: int = 0,
) -> tuple[POICandidate | None, POICandidate | None, POICandidate | None]:
    """返回 (breakfast, lunch, dinner) 候选，三餐+跨天不重复。"""
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

    if pc.cuisine_preferences:
        cuisine_matched = [
            r for r in affordable
            if any(_record_matches_restaurant_type(r.metadata or {}, pref) for pref in pc.cuisine_preferences)
        ]
        if cuisine_matched:
            affordable = cuisine_matched

    required_restaurants = _ordered_required_restaurants(restaurants, pc.required_restaurant_names)
    if required_restaurants:
        start = (day_index * 2) % len(required_restaurants)
        required_restaurants = required_restaurants[start:] + required_restaurants[:start]
        required_names = {r.name for r in required_restaurants}
        fillers = [r for r in affordable if r.name not in required_names and r.name not in _used_restaurant_names]
        if not fillers:
            fillers = [r for r in affordable if r.name not in required_names]
        fallback = fillers + affordable + required_restaurants
        breakfast_r = fallback[0] if fallback else required_restaurants[0]
        lunch_r = required_restaurants[0]
        dinner_r = required_restaurants[1] if len(required_restaurants) > 1 else (fallback[1] if len(fallback) > 1 else lunch_r)
        for r in (breakfast_r, lunch_r, dinner_r):
            if r and r.name not in required_names:
                _used_restaurant_names.add(r.name)
        return breakfast_r, lunch_r, dinner_r

    affordable = sorted(affordable, key=lambda r: _poi_price(r))
    skill_result = select_meal_candidates(
        affordable,
        people=pc.people,
        dining_budget=pc.dining_budget,
        used_names=_used_restaurant_names,
    )
    by_id = {r.poi_id: r for r in affordable}
    breakfast_r = by_id.get(skill_result.decision.get("breakfast_id"))
    lunch_r = by_id.get(skill_result.decision.get("lunch_id"))
    dinner_r = by_id.get(skill_result.decision.get("dinner_id"))
    if not all((breakfast_r, lunch_r, dinner_r)):
        # 优先选未用过的餐厅
        fresh = [r for r in affordable if r.name not in _used_restaurant_names]
        if not fresh:
            fresh = affordable  # 都用过了就循环
        # 选三个不同餐厅
        if len(fresh) >= 3:
            breakfast_r, lunch_r, dinner_r = fresh[0], fresh[1], fresh[2]
        elif len(fresh) == 2:
            breakfast_r, lunch_r, dinner_r = fresh[0], fresh[1], fresh[0]
        else:
            breakfast_r = lunch_r = dinner_r = fresh[0]
    # 标记已用
    for r in (breakfast_r, lunch_r, dinner_r):
        if r:
            _used_restaurant_names.add(r.name)
    return breakfast_r, lunch_r, dinner_r


def _ordered_required_restaurants(
    restaurants: list[POICandidate],
    required_names: list[str],
) -> list[POICandidate]:
    if not restaurants or not required_names:
        return []
    ordered: list[POICandidate] = []
    used: set[str] = set()
    for name in required_names:
        match = next((r for r in restaurants if r.name not in used and _candidate_matches_name(r, [name])), None)
        if match:
            ordered.append(match)
            used.add(match.name)
    return ordered


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

    # Free attraction: strongly prefer price=0 POIs
    if pc.free_attraction:
        others.sort(key=lambda p: (_poi_price(p, 0.0), -p.score))
    elif policy == "budget":
        others.sort(key=lambda p: (_poi_price(p, 0.0), -p.score))
    else:
        others.sort(key=lambda p: -p.score)

    ordered_remaining = _dedupe_candidates(must + others)
    lock_result = lock_must_visit_order(ordered_remaining, pc.must_visit, pc.must_visit_types)
    ordered_ids = lock_result.decision.get("ordered_poi_ids") or []
    if ordered_ids:
        by_id = {p.poi_id: p for p in ordered_remaining}
        reordered = [by_id[pid] for pid in ordered_ids if pid in by_id]
        if len(reordered) == len(ordered_remaining):
            ordered_remaining = reordered
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

    return _rebalance_must_visit_days(days, pc)


def _rebalance_must_visit_days(
    days: list[list[POICandidate]],
    pc: PlanningConstraints,
) -> list[list[POICandidate]]:
    if not days or not (pc.must_visit or pc.must_visit_types):
        return days

    target_indices = list(range(1, len(days) - 1)) if len(days) > 2 else list(range(len(days)))
    if not target_indices:
        return days

    must_items: list[POICandidate] = []
    seen_must: set[str] = set()
    rebuilt: list[list[POICandidate]] = []
    for day_items in days:
        keep: list[POICandidate] = []
        for poi in day_items:
            if _is_must_poi(poi, pc):
                key = poi.poi_id or poi.name
                if key not in seen_must:
                    seen_must.add(key)
                    must_items.append(poi)
            else:
                keep.append(poi)
        rebuilt.append(keep)

    for idx, poi in enumerate(must_items):
        day_idx = target_indices[idx % len(target_indices)]
        rebuilt[day_idx].insert(0, poi)

    return [_dedupe_candidates(day_items) for day_items in rebuilt]


def _daily_capacity(policy: str, pace_weight: float, pc: PlanningConstraints, *, is_final_day: bool) -> int:
    # TEMP_v1: +1 POI per day for better DDR
    if pc.max_pois_per_day:
        cap = pc.max_pois_per_day
    elif policy == "safe" or pc.pace == "relaxed" or pace_weight < 0.4:
        cap = 3
    elif policy == "preference" or pc.pace == "intensive" or pace_weight > 0.6:
        cap = 5
    else:
        cap = 4
    if policy == "budget":
        cap = min(cap, 3)
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
    if any(_name_matches(poi.name, m) or m.lower() == pid_l for m in pc.must_visit):
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
    modes = ["metro", "taxi", "walk"]
    if use_taxi:
        modes = ["taxi", "metro", "walk"]
    segments = None
    for mode in modes:
        segments = sandbox.goto(
            city, start, end, start_time, mode,
            people=pc.people, taxi_cars=pc.taxi_cars,
        )
        if segments:
            break
    end_time = segments[-1]["end_time"] if segments else start_time
    return normalize_transports(segments or [], pc.people, pc.taxi_cars), end_time


def rebuild_local_transports(
    activities: list[dict[str, Any]],
    sandbox: SandboxClient,
    pc: PlanningConstraints,
) -> list[dict[str, Any]]:
    """Post-generation: rebuild all inner-city transports in order.

    Rules:
    1. Every position change MUST have transport.
    2. transport[0].start == previous activity's position or end.
    3. transport[-1].end == current activity's position.
    4. activity.start_time = transport[-1].end_time.
    5. Keep WorldEnv price/cost/distance/duration values.
    6. On goto failure: try taxi→metro→walk→delete non-essential activity.
    """
    if not activities:
        return activities

    city = pc.target_city
    rebuilt: list[dict[str, Any]] = []
    prev_pos = ""
    prev_end_pos = ""

    for idx, act in enumerate(activities):
        atype = act.get("type", "")
        act_pos = str(act.get("position", ""))

        # Intercity transport: no local transport needed before it
        if atype in ("airplane", "train"):
            rebuilt.append(dict(act))
            prev_pos = str(act.get("end", act.get("start", "")))
            prev_end_pos = prev_pos
            continue

        if idx == 0:
            # First activity: if it has a position, transport from prev_pos
            rebuilt.append(dict(act))
            prev_pos = act_pos or prev_pos
            prev_end_pos = prev_pos
            continue

        # Determine "from" position for this activity
        from_pos = prev_end_pos or prev_pos
        to_pos = act_pos

        if not from_pos or not to_pos or from_pos == to_pos:
            # Same position or no position info — no transport needed
            rebuilt.append(dict(act))
            prev_pos = act_pos or from_pos
            prev_end_pos = to_pos or prev_pos
            continue

        # Build transport between from_pos → to_pos
        start_t = act.get("start_time", "09:00")
        transports: list[dict] = []
        try:
            for mode in ("metro", "taxi", "walk"):
                segs = sandbox.goto(city, from_pos, to_pos, start_t, mode,
                                    people=pc.people, taxi_cars=pc.taxi_cars)
                if segs:
                    transports = segs
                    break
        except Exception:
            pass

        if not transports:
            # goto failed entirely: set walk as minimal fallback
            transports = [{
                "start": from_pos, "end": to_pos, "mode": "walk",
                "start_time": start_t,
                "end_time": add_minutes(start_t, 20),
                "cost": 0.0, "price": 0.0, "distance": 1.5,
            }]

        # transport continuity: set start/end correctly
        if not transports[0].get("start"):
            transports[0]["start"] = from_pos
        if not transports[-1].get("end"):
            transports[-1]["end"] = to_pos

        arrive_time = transports[-1]["end_time"] if transports else start_t

        # Update activity transports only; keep original start/end times if valid
        new_act = dict(act)
        new_act["transports"] = normalize_transports(transports, pc.people, pc.taxi_cars)
        # Only set start_time from transport arrival if it improves the schedule
        orig_start = act.get("start_time", "")
        if orig_start and time_to_minutes(arrive_time) > time_to_minutes(orig_start):
            new_act["start_time"] = arrive_time
        elif not orig_start:
            new_act["start_time"] = arrive_time

        rebuilt.append(new_act)
        prev_pos = to_pos
        prev_end_pos = to_pos

    return rebuilt


def _activity_duration(act: dict[str, Any]) -> int:
    """Estimate activity duration in minutes."""
    atype = act.get("type", "")
    if atype in ("breakfast",):
        return 45
    if atype in ("lunch", "dinner"):
        return 60
    if atype == "accommodation":
        return 60
    if atype == "attraction":
        return 90
    try:
        start = time_to_minutes(act.get("start_time", "00:00"))
        end = time_to_minutes(act.get("end_time", "00:45"))
        return max(30, end - start)
    except Exception:
        return 60


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
    if restaurant is None:
        is_real_hotel_breakfast = meal_type == "breakfast" and fallback_name and "Spot" not in fallback_name
        if not is_real_hotel_breakfast:
            raise RuntimeError(f"no real restaurant for {meal_type}")
        name = fallback_name
        price = 0.0
    else:
        name = restaurant.name
        price = _poi_price(restaurant, 35.0 if meal_type == "breakfast" else 50.0)
    duration = 45 if meal_type == "breakfast" else 60

    # 餐点时间窗口（commonsense 约束: breakfast<09:00, lunch[11:00,14:00], dinner[17:00,20:00]）
    meal_windows = {"breakfast": ("07:00", "09:00"), "lunch": ("11:00", "14:00"), "dinner": ("17:00", "20:00")}
    win_start, win_end = meal_windows.get(meal_type, ("07:00", "21:00"))

    # 如果当前时间已超过窗口结束（含容错：breakfast 需 strict <09:00），跳过该餐
    if meal_type == "breakfast":
        if time_to_minutes(current_time) >= time_to_minutes("08:59"):
            raise RuntimeError(f"breakfast window closed: current={current_time} >= 08:59")
    elif time_to_minutes(current_time) >= time_to_minutes(win_end):
        raise RuntimeError(f"{meal_type} window closed: current={current_time} >= end={win_end}")

    # 推后到窗口起始时间
    current_time = max_time(current_time, win_start)

    if restaurant and not sandbox.is_restaurant_open(pc.target_city, name, current_time):
        # 如果餐厅未营业且未超窗口，尝试多次后推（最多3次，每次15分钟）
        pushed = current_time
        opened = False
        for _ in range(3):
            pushed = add_minutes(pushed, 15, allow_overflow=False)
            if time_to_minutes(pushed) >= time_to_minutes(win_end):
                break
            if sandbox.is_restaurant_open(pc.target_city, name, pushed):
                current_time = pushed
                opened = True
                break
        if not opened:
            current_time = max_time(current_time, win_start)

    try:
        transports, arrive = _goto(sandbox, pc, pc.target_city, pos, name, current_time)
        # activity start_time = transport 到达时间（非出发时间）
        t_end = add_minutes(arrive, duration)
        # 如果结束时间超过窗口，尝试缩短持续时间
        if time_to_minutes(t_end) > time_to_minutes(win_end):
            t_end = win_end
        # Critical guard: end_time must be > start_time
        if time_to_minutes(t_end) <= time_to_minutes(arrive):
            t_end = add_minutes(arrive, max(15, duration // 2))
            if time_to_minutes(t_end) > time_to_minutes(win_end):
                t_end = win_end
        if time_to_minutes(t_end) <= time_to_minutes(arrive):
            raise RuntimeError(f"meal duration infeasible: arrive={arrive} end={t_end}")
        activities.append(make_activity(
            meal_type, arrive, t_end,
            price * pc.people, price, transports,
            position=name, tickets=pc.people,
        ))
        next_time = add_minutes(t_end, 10)
        return name, next_time
    except RuntimeError:
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
    current_time: str = "08:30",
    prev_position: str = "",
    skip_breakfast: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    """构建单日 activity（餐饮/景点/住宿），满足票务与交通约束。"""
    target = pc.target_city
    activities: list[dict[str, Any]] = []
    pos = prev_position or (hotel.name if hotel else "")
    breakfast_r, lunch_r, dinner_r = meals

    # 根据当前时间决定跳过哪些餐
    cur_min = time_to_minutes(current_time)
    skip_lunch = cur_min >= time_to_minutes("14:00")  # 14:00 后跳过午餐
    skip_dinner = cur_min >= time_to_minutes("21:00")  # 21:00 后跳过晚餐

    # Breakfast is mandatory except Day 1 late arrival
    actual_skip_breakfast = skip_breakfast and day_index == 0
    # Breakfast is mandatory for non-arrival days. Force insert even if transport fails.
    if not actual_skip_breakfast:
        inserted = False
        for attempt in range(2):
            try:
                pos, current_time = _append_meal(
                    activities, "breakfast", breakfast_r, sandbox, pc, pos,
                    max_time(current_time, "07:30"),
                    hotel.name if hotel else f"{target} Breakfast Spot",
                )
                inserted = True
                break
            except RuntimeError:
                if attempt == 0:
                    # Retry with forced early time and no transport
                    try:
                        bf_name = breakfast_r.name if breakfast_r else (hotel.name if hotel else "")
                        if not bf_name:
                            raise RuntimeError("no real breakfast fallback")
                        bf_price = _poi_price(breakfast_r, 35.0) if breakfast_r else 0.0
                        activities.append(make_activity(
                            "breakfast", "08:00", "08:45",
                            bf_price * pc.people, bf_price, [],
                            position=bf_name, tickets=pc.people,
                        ))
                        pos = bf_name
                        current_time = "08:55"
                        inserted = True
                    except Exception:
                        pass
                break
        if not inserted and pos and time_to_minutes(current_time) < time_to_minutes("11:00"):
            current_time = "11:00"
    elif pos and time_to_minutes(current_time) < time_to_minutes("11:00"):
        current_time = "11:00"

    if not day_pois and not skip_lunch:
        try:
            pos, current_time = _append_meal(
                activities, "lunch", lunch_r, sandbox, pc, pos, current_time,
                f"{target} Lunch Spot",
            )
        except RuntimeError:
            pass

    skipped_pois = 0
    for i, poi in enumerate(day_pois):
        # 防护：跳过无名/无效 POI（幽灵活动来源）
        if not poi or not poi.name or not poi.name.strip():
            skipped_pois += 1
            continue

        meta = poi.metadata or {}
        visit_min = 90
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

        # 开放时间检查：如果景点未开放，尝试后推到开门时间
        poi_open_t = str(meta.get("opentime", "09:00"))
        poi_close_t = str(meta.get("endtime", "24:00"))
        if not sandbox.is_attraction_open(target, poi.name, current_time):
            # 尝试后推到开门时间
            if time_to_minutes(current_time) < time_to_minutes(poi_open_t):
                candidate_time = max_time(current_time, poi_open_t)
                # 验证后推后是否在开放时间内且有足够参观时间
                if (sandbox.is_attraction_open(target, poi.name, candidate_time)
                        and time_to_minutes(add_minutes(candidate_time, visit_min)) <= time_to_minutes(poi_close_t)):
                    current_time = candidate_time
                else:
                    skipped_pois += 1
                    continue  # 无法安排，跳过此 POI
            else:
                skipped_pois += 1
                continue  # 已关门，跳过此 POI

        # 如果当前时间已超过关门时间减去最小参观时长，跳过
        if time_to_minutes(current_time) + visit_min > time_to_minutes(poi_close_t):
            skipped_pois += 1
            continue

        try:
            transports, arrive = _goto(sandbox, pc, target, pos, poi.name, current_time)
            # transport 不可达且非必去 → 跳过
            is_must = _is_must_poi(poi, pc)
            if not transports and not is_must:
                skipped_pois += 1
                continue
            # activity start_time = 到达时间（非 transport 出发时间）
            t_end = add_minutes(arrive, visit_min)
            price = _poi_price(poi, 0.0)
            activities.append(make_activity(
                "attraction", arrive, t_end,
                price * pc.people, price, transports,
                position=poi.name, tickets=pc.activity_tickets or pc.people,
            ))
            pos = poi.name
            current_time = add_minutes(t_end, pc.buffer_minutes)
        except RuntimeError:
            skipped_pois += 1
            continue  # 时间溢出，跳过此 POI

        if i == 0 and not skip_lunch:
            try:
                pos, current_time = _append_meal(
                    activities, "lunch", lunch_r, sandbox, pc, pos, current_time,
                    f"{target} Lunch Spot",
                )
            except RuntimeError:
                pass

    if not skip_dinner:
        try:
            pos, current_time = _append_meal(
                activities, "dinner", dinner_r, sandbox, pc, pos,
                max_time(current_time, "17:30"),
                f"{target} Dinner Spot",
            )
        except RuntimeError:
            pass

    if day_index < num_days and hotel:
        try:
            at0 = max_time(current_time, "20:00")
            hp = _poi_price(hotel, 300.0)
            transports, arrive = _goto(
                sandbox, pc, target, pos, hotel.name, at0, use_taxi=True,
            )
            at1 = add_minutes(arrive, 60)
            if time_to_minutes(at1) <= time_to_minutes(arrive):
                at1 = add_minutes(arrive, 120)
            rooms = max(1, (pc.people + 1) // 2)
            # room_type 必须匹配数据库 numbed 字段（床数），不是硬编码 1
            meta = hotel.metadata or {}
            room_type = int(meta.get("numbed", meta.get("room_type", 1)))
            activities.append(make_activity(
                "accommodation", arrive, at1,
                hp * rooms, hp, transports,
                position=hotel.name, tickets=pc.people,
                extra={"rooms": rooms, "room_type": room_type},
            ))
            pos = hotel.name
        except RuntimeError:
            pass  # 住宿排不下，跳过

    # Rebuild transports for continuity before returning
    activities = rebuild_local_transports(activities, sandbox, pc)
    return activities, pos


def build_full_plan_dict(
    constraints: Constraints,
    candidates: CandidatePool,
    preferences,
    policy: str = "safe",
) -> dict[str, Any]:
    """构建完整官方 plan 字典。"""
    _reset_restaurant_tracker()
    pc = extract_planning_constraints(constraints)
    lang = infer_lang(pc.target_city or pc.start_city)
    sandbox = get_sandbox(lang)

    pois, hotels, restaurants = _ensure_candidates(sandbox, pc.target_city, candidates, pc)
    hotel = _select_hotel(sandbox, pc, hotels)

    pace = getattr(preferences, "pace_weight", 0.5)
    poi_by_day = _pick_pois_per_day(pois, pc.days, pc, policy, pace)

    itinerary: list[dict] = []
    prev_pos = hotel.name if hotel else ""
    hotel_anchor = prev_pos
    last_day_end_time = "18:00"

    for day_idx in range(pc.days):
        day_num = day_idx + 1
        acts: list[dict] = []
        # 每天重置时间和选新餐厅（避免跨天重复）
        current_time = "09:00"
        skip_breakfast = False
        meals = _select_restaurants(pc, restaurants, day_index=day_idx)

        if day_idx == 0:
            go = sandbox.select_intercity(
                pc.start_city, pc.target_city, pc.intercity_mode, "06:00",
            )
            if go:
                acts.append(make_intercity_activity(go, pc.people))
                prev_pos = _intercity_end_position(go, pc.target_city)
                raw_end = go.get("EndTime") or go.get("end_time") or "10:30"
                try:
                    current_time = add_minutes(raw_end, 30, allow_overflow=True)
                    if time_to_minutes(current_time) >= 24 * 60:
                        current_time = "20:00"  # 跨日到达：只住宿，不塞活动
                except RuntimeError:
                    current_time = "20:00"
                skip_breakfast = time_to_minutes(current_time) >= time_to_minutes("10:00")

                # 晚到硬规则：>= 18:00 只安排住宿；>= 16:30 最多 1 个景点
                late_arrival = time_to_minutes(current_time) >= time_to_minutes("18:00")
                limited_arrival = time_to_minutes(current_time) >= time_to_minutes("16:30")

            light_decision = cross_city_day_light_plan({
                "arrival_time": current_time,
                "policy": policy,
                "poi_count": len(poi_by_day[day_idx]),
            }).decision
            # 晚到硬规则：>=18:00 仅住宿；>=16:30 最多 1 POI
            late_arrival = time_to_minutes(current_time) >= time_to_minutes("18:00")
            limited_arrival = time_to_minutes(current_time) >= time_to_minutes("16:30")
            if late_arrival:
                day_acts, prev_pos = build_day_activities(
                    day_num, pc.days, [], hotel, meals, pc, sandbox,
                    current_time=current_time,
                    prev_position=prev_pos,
                    skip_breakfast=True,
                )
            elif limited_arrival:
                day_acts, prev_pos = build_day_activities(
                    day_num, pc.days, poi_by_day[day_idx][:1], hotel, meals, pc, sandbox,
                    current_time=current_time,
                    prev_position=prev_pos,
                    skip_breakfast=skip_breakfast,
                )
            elif light_decision.get("light_day") and int(light_decision.get("allowed_pois", 0)) <= 0:
                day_acts, prev_pos = build_day_activities(
                    day_num, pc.days, [], hotel, meals, pc, sandbox,
                    current_time=current_time,
                    prev_position=prev_pos,
                    skip_breakfast=True,
                )
            else:
                allowed = int(light_decision.get("allowed_pois", len(poi_by_day[day_idx])))
                day_acts, prev_pos = build_day_activities(
                    day_num, pc.days, poi_by_day[day_idx][:allowed], hotel, meals, pc, sandbox,
                    current_time=current_time,
                    prev_position=prev_pos,
                    skip_breakfast=skip_breakfast,
                )
        else:
            prev_pos = hotel_anchor or prev_pos
            current_time = "08:30"
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

            # 尝试城际返程，确保出发时间晚于当天最后一个活动
            back = None
            for try_earliest in (back_time, "18:00", "16:00", "14:00", "12:00", "10:00", "08:00"):
                try:
                    candidate = sandbox.select_intercity(
                        pc.target_city, pc.start_city, pc.intercity_mode, try_earliest,
                    )
                    if candidate:
                        # 手动过滤：出发时间必须不早于请求的最早时间
                        depart_time = candidate.get("BeginTime") or candidate.get("start_time") or "00:00"
                        if time_to_minutes(depart_time) < time_to_minutes(try_earliest):
                            continue  # 跳过过早的车次
                        back = candidate
                        break
                except Exception:
                    continue
            if back:
                # 如果返程出发早于最后活动结束，删除最后冲突的活动
                depart_time = back.get("BeginTime") or back.get("start_time") or "00:00"
                acts_to_keep = []
                for a in acts:
                    a_end = a.get("end_time", "00:00")
                    if time_to_minutes(a_end) + 60 <= time_to_minutes(depart_time):
                        acts_to_keep.append(a)
                    else:
                        break  # 该活动及其后活动都会冲突
                if len(acts_to_keep) < len(acts):
                    acts = acts_to_keep
                try:
                    acts.append(make_intercity_activity(back, pc.people, is_return=True))
                except (ValueError, RuntimeError):
                    pass

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
