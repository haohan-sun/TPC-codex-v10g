"""Daily route optimization for travel plans.

The route-planning migration happens here: attractions are route nodes, travel
time/distance is edge cost, and meals/hotel/intercity activities are fixed
schedule anchors.  We reorder only attraction activities, then re-time local
segments so the official activity structure remains valid.

Current solver: greedy nearest-neighbor + 2-opt local search.

Future GA-TSP integration point:
    Replace ``_optimized_attraction_order()`` with a GA-TSP solver that accepts
    the interface defined in ``src/optimizer/ga_tsp_interface.py``.
    Key inputs: DayAttraction list, TransportMatrix, start/end position,
                opening hours, must_visit flags.
    The rest of the day-level orchestration (_retime_day, meal anchors, etc.)
    remains unchanged.
"""

from __future__ import annotations

from typing import Any

from src.data_layer.chinatravel_bridge import infer_lang
from src.data_layer.schema import Plan
from src.data_layer.world_env_client import get_sandbox
from src.optimizer.ga_tsp import solve_ga_tsp
from src.optimizer.ga_tsp_interface import DayAttraction, GATSPConfig, TransportMatrix, build_transport_matrix_spec
from src.optimizer.nearest_neighbor import nearest_neighbor_route
from src.optimizer.two_opt import two_opt
from src.planner.plan_utils import add_minutes, max_time, normalize_transports, time_to_minutes


MEAL_MIN_START = {"breakfast": "07:30", "lunch": "11:30", "dinner": "17:30"}


def _goto_best(
    sandbox,
    city: str,
    start: str,
    end: str,
    start_time: str,
    *,
    people: int,
    taxi_cars: int,
    prefer_metro: bool = True,
) -> list[dict[str, Any]]:
    if not start or not end or start == end:
        return []
    modes = ["metro", "taxi", "walk"] if prefer_metro else ["taxi", "metro", "walk"]
    for mode in modes:
        try:
            transports = sandbox.goto(
                city, start, end, start_time, mode,
                people=people, taxi_cars=taxi_cars,
            )
            if transports:
                return normalize_transports(transports, people, taxi_cars)
        except Exception:
            continue
    return []


def _find_open_start(
    sandbox,
    city: str,
    position: str,
    start_time: str,
    latest_time: str,
    *,
    is_restaurant: bool,
    step_min: int = 15,
) -> str | None:
    current = start_time
    checker = sandbox.is_restaurant_open if is_restaurant else sandbox.is_attraction_open
    while time_to_minutes(current) < time_to_minutes(latest_time):
        try:
            if checker(city, position, current):
                return current
        except Exception:
            return current
        try:
            current = add_minutes(current, step_min)
        except RuntimeError:
            return None
    return None


def _open_for_whole_activity(
    sandbox,
    city: str,
    position: str,
    start_time: str,
    end_time: str,
    *,
    is_restaurant: bool,
) -> bool:
    checker = sandbox.is_restaurant_open if is_restaurant else sandbox.is_attraction_open
    try:
        end_probe = add_minutes(end_time, -1)
    except RuntimeError:
        end_probe = end_time
    try:
        return bool(checker(city, position, start_time) and checker(city, position, end_probe))
    except Exception:
        return True


def optimize_daily_routes(plan: Plan) -> Plan:
    """Optimize attraction order inside each day using NN + 2-opt."""
    official = plan.metadata.get("official_plan") or {}
    itinerary = official.get("itinerary") or []
    city = official.get("target_city") or ""
    if not city:
        return plan

    sandbox = get_sandbox(infer_lang(city))
    poi_meta = _poi_meta_by_name(plan)

    overnight_pos = ""
    for day in itinerary:
        activities = day.get("activities") or []
        attraction_slots = [i for i, a in enumerate(activities) if a.get("type") == "attraction"]
        if len(attraction_slots) >= 2:
            ordered = _optimized_attraction_order(
                [activities[i] for i in attraction_slots],
                city,
                sandbox,
                poi_meta,
                _start_anchor_for_day(activities, attraction_slots[0]),
                plan=plan,
            )
            for slot, act in zip(attraction_slots, ordered):
                activities[slot] = act
        end_pos = _retime_day(activities, city, sandbox, plan, overnight_pos, poi_meta)
        # 清理被标记跳过的餐
        day["activities"] = [
            a for a in activities
            if not a.pop("_skip_meal", False) and not a.pop("_skip_activity", False)
        ]
        overnight_pos = _overnight_position(day["activities"]) or end_pos

    plan.metadata["official_plan"] = official
    return plan


def _optimized_attraction_order(
    attraction_acts: list[dict[str, Any]],
    city: str,
    sandbox,
    poi_meta: dict[str, dict[str, Any]],
    start_anchor: str,
    plan: Any = None,
) -> list[dict[str, Any]]:
    by_name = {str(a.get("position", "")): a for a in attraction_acts if a.get("position")}
    names = list(by_name)
    if len(names) <= 1:
        return attraction_acts

    matrix = {
        (a, b): _distance(city, a, b, sandbox, poi_meta)
        for a in names
        for b in names
        if a != b
    }

    # GA-TSP for >=3 attractions
    if len(names) >= 3:
        ga_names = _try_ga_tsp(attraction_acts, names, city, sandbox, poi_meta, start_anchor, plan)
        if ga_names and len(ga_names) == len(names):
            return [by_name[n] for n in ga_names if n in by_name]

    greedy = _greedy_from_anchor(names, start_anchor, city, sandbox, poi_meta)
    optimized_names = two_opt(greedy, matrix)
    return [by_name[n] for n in optimized_names if n in by_name]


def _try_ga_tsp(
    attraction_acts, names, city, sandbox, poi_meta, start_anchor, plan=None,
) -> list[str] | None:
    """GA-TSP 优化，参数根据 deadline 自适应缩小。"""
    try:
        must_visit: set[str] = set()
        if plan is not None:
            pc = (plan.metadata.get("official_plan") or {}).get("_planning_constraints")
            if pc:
                for mv in (getattr(pc, "must_visit", []) or []):
                    must_visit.add(str(mv))
        day_attrs = []
        for act in attraction_acts:
            name = str(act.get("position", ""))
            if not name:
                continue
            meta = poi_meta.get(name, {})
            day_attrs.append(DayAttraction(
                name=name,
                opening_time=str(meta.get("opentime", "09:00")),
                closing_time=str(meta.get("endtime", "18:00")),
                duration_min=max(45, int(float(meta.get("recommendmintime", 1.5)) * 60)),
                must_visit=name in must_visit,
                price=float(meta.get("price", 0)),
                tickets=int(act.get("tickets", 1)),
                metadata=meta,
            ))
        if len(day_attrs) < 3:
            return None

        # 检查剩余时间，自适应缩小 GA 参数
        remaining = 120.0  # default generous
        if plan and plan.metadata.get("deadline"):
            import time as _time
            dl = plan.metadata["deadline"].get("deadline_end", 0)
            remaining = max(0, dl - _time.monotonic())

        if remaining > 60:
            pop, gen, stall, tsec = 40, 150, 25, 8.0
        elif remaining > 30:
            pop, gen, stall, tsec = 20, 80, 12, 4.0
        elif remaining > 10:
            pop, gen, stall, tsec = 12, 30, 8, 2.0
        else:
            # 时间太紧，跳过 GA-TSP，直接 fallback 到 NN+2opt
            return None

        tmatrix = build_transport_matrix_spec(day_attrs, sandbox, city)
        ga_config = GATSPConfig(
            population_size=pop, generations=gen, mutation_rate=0.15,
            crossover_rate=0.80, elite_count=min(4, max(1, pop // 8)),
            tournament_size=3, max_stall_generations=stall, timeout_sec=tsec,
        )
        ordered_names, _ = solve_ga_tsp(
            day_attrs=day_attrs, transport_matrix=tmatrix,
            start_position=start_anchor, config=ga_config,
        )
        if ordered_names and len(ordered_names) == len(names):
            return ordered_names
    except Exception:
        pass
    return None


def _greedy_from_anchor(
    names: list[str],
    start_anchor: str,
    city: str,
    sandbox,
    poi_meta: dict[str, dict[str, Any]],
) -> list[str]:
    if not start_anchor:
        return nearest_neighbor_route(names, _pairwise_matrix(names, city, sandbox, poi_meta))
    unvisited = set(names)
    current = start_anchor
    route: list[str] = []
    while unvisited:
        nxt = min(unvisited, key=lambda n: _distance(city, current, n, sandbox, poi_meta))
        route.append(nxt)
        unvisited.remove(nxt)
        current = nxt
    return route


def _pairwise_matrix(names: list[str], city: str, sandbox, poi_meta: dict[str, dict[str, Any]]) -> dict[tuple[str, str], float]:
    return {(a, b): _distance(city, a, b, sandbox, poi_meta) for a in names for b in names if a != b}


def _start_anchor_for_day(activities: list[dict[str, Any]], first_attraction_slot: int) -> str:
    for act in reversed(activities[:first_attraction_slot]):
        if act.get("position"):
            return str(act["position"])
        if act.get("end"):
            return str(act["end"])
    return ""


def _poi_meta_by_name(plan: Plan) -> dict[str, dict[str, Any]]:
    candidates = plan.metadata.get("candidates")
    meta: dict[str, dict[str, Any]] = {}
    for attr in ("pois", "hotels", "restaurants"):
        for item in getattr(candidates, attr, []) or []:
            if item.name:
                meta[item.name] = item.metadata or {}
    return meta


def _distance(city: str, a: str, b: str, sandbox, poi_meta: dict[str, dict[str, Any]]) -> float:
    """两点距离（km），优先坐标 Haversine，次选缓存 sandbox，最后 fallback 3km。"""
    if not a or not b or a == b:
        return 0.0
    # 1. 优先：坐标 Haversine（快，纯计算，不调后端）
    ca, cb = _coords(poi_meta.get(a, {})), _coords(poi_meta.get(b, {}))
    if ca and cb:
        import math
        r = 6371.0
        phi1, phi2 = math.radians(ca[0]), math.radians(cb[0])
        dphi = math.radians(cb[0] - ca[0])
        dlambda = math.radians(cb[1] - ca[1])
        x = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        return 2 * r * math.asin(math.sqrt(x))
    # 2. 次选：sandbox（已缓存，但 cold 时较慢）
    try:
        dist = sandbox.poi_distance(city, a, b, "09:00", "metro")
        if dist is not None and dist > 0:
            return float(dist)
    except Exception:
        pass
    return 3.0


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


def _retime_day(activities: list[dict[str, Any]], city: str, sandbox, plan: Plan, start_pos: str = "", poi_meta: dict | None = None) -> str:
    """重排当天活动时间。城际交通保留原始真实时间。"""
    current_time = _initial_day_time(activities)
    current_pos = start_pos
    pc = (plan.metadata.get("official_plan") or {}).get("_planning_constraints")
    people = getattr(pc, "people", 1)
    taxi_cars = getattr(pc, "taxi_cars", max(1, (people + 3) // 4))
    prefer_metro = getattr(pc, "prefer_metro", True)
    meal_deadlines = {"breakfast": "09:00", "lunch": "14:00", "dinner": "20:00"}

    for act_idx, act in enumerate(activities):
        atype = act.get("type", "")

        if atype in ("airplane", "train"):
            is_arrival = (act_idx == 0)
            if is_arrival:
                arrival_station = _intercity_arrival_station(act)
                if arrival_station:
                    current_pos = arrival_station
                raw_end = act.get("end_time", current_time)
                try:
                    current_time = add_minutes(raw_end, 30)
                except RuntimeError:
                    current_time = max_time(current_time, "20:00")
            else:
                departure_station = _intercity_departure_station(act)
                intercity_depart = act.get("start_time", "")
                if current_pos and departure_station and current_pos != departure_station:
                    if (not intercity_depart or
                            time_to_minutes(intercity_depart) >= time_to_minutes(current_time)):
                        try:
                            station_transports = sandbox.goto(
                                city, current_pos, departure_station, current_time, "taxi",
                                people=people, taxi_cars=taxi_cars,
                            )
                            if station_transports:
                                act["transports"] = normalize_transports(station_transports, people, taxi_cars)
                        except Exception:
                            pass
            continue

        if atype in MEAL_MIN_START:
            current_time = max_time(current_time, MEAL_MIN_START[atype])
        if atype == "accommodation":
            current_time = max_time(current_time, "20:00")

        # 餐点窗口死线
        if atype in meal_deadlines and time_to_minutes(current_time) >= time_to_minutes(meal_deadlines[atype]):
            act["_skip_meal"] = True
            continue

        position = str(act.get("position", ""))
        if position:
            try:
                transports = _goto_best(
                    sandbox, city, current_pos, position, current_time,
                    people=people,
                    taxi_cars=taxi_cars,
                    prefer_metro=prefer_metro and atype != "accommodation",
                )
                if current_pos and current_pos != position and not transports:
                    if atype in meal_deadlines:
                        act["_skip_meal"] = True
                    else:
                        act["_skip_activity"] = True
                    continue
                act["transports"] = transports
                arrive = act["transports"][-1]["end_time"] if act["transports"] else current_time

                # 餐点死线二次检查
                if atype in meal_deadlines and time_to_minutes(arrive) >= time_to_minutes(meal_deadlines[atype]):
                    act["_skip_meal"] = True
                    continue

                # KEY FIX: activity start = transport ARRIVE time, NOT departure time
                act["start_time"] = arrive

                # 景点：验证开放时间（仅对 attraction，不对 meal 用 opentime）
                if atype == "attraction" and position in (poi_meta or {}):
                    open_t = (poi_meta or {}).get(position, {}).get("opentime", "00:00")
                    close_t = (poi_meta or {}).get(position, {}).get("endtime", "24:00")
                    if time_to_minutes(arrive) < time_to_minutes(open_t):
                        act["start_time"] = open_t
                    if time_to_minutes(act["start_time"]) >= time_to_minutes(close_t):
                        act["_skip_activity"] = True
                        continue  # 已关门，跳过
                elif atype == "attraction":
                    open_start = _find_open_start(
                        sandbox, city, position, act["start_time"], "22:00",
                        is_restaurant=False,
                    )
                    if not open_start:
                        act["_skip_activity"] = True
                        continue
                    act["start_time"] = open_start

                # 餐厅营业验证
                if atype in ("breakfast", "lunch", "dinner") and position:
                    try:
                        if not sandbox.is_restaurant_open(city, position, act["start_time"]):
                            pushed = _find_open_start(
                                sandbox, city, position, act["start_time"],
                                meal_deadlines.get(atype, "23:59"),
                                is_restaurant=True,
                            )
                            if pushed:
                                act["start_time"] = pushed
                            else:
                                act["_skip_meal"] = True
                                continue
                    except Exception:
                        pass

                act["end_time"] = add_minutes(act["start_time"], _activity_duration(act))

                # 餐点截止截断
                if atype in meal_deadlines and time_to_minutes(act["end_time"]) > time_to_minutes(meal_deadlines[atype]):
                    act["end_time"] = meal_deadlines[atype]
                if atype in meal_deadlines and not _open_for_whole_activity(
                    sandbox, city, position, act["start_time"], act["end_time"],
                    is_restaurant=True,
                ):
                    act["_skip_meal"] = True
                    continue

                # 关门截断
                if atype == "attraction" and position in (poi_meta or {}):
                    close_t2 = (poi_meta or {}).get(position, {}).get("endtime", "24:00")
                    if time_to_minutes(act["end_time"]) > time_to_minutes(close_t2):
                        act["end_time"] = close_t2
                if atype == "attraction" and not _open_for_whole_activity(
                    sandbox, city, position, act["start_time"], act["end_time"],
                    is_restaurant=False,
                ):
                    act["_skip_activity"] = True
                    continue

                # 守卫：end > start
                if time_to_minutes(act["end_time"]) <= time_to_minutes(act["start_time"]):
                    if atype == "attraction":
                        act["_skip_activity"] = True
                        continue
                    act["end_time"] = add_minutes(act["start_time"], 30)
                    if atype in meal_deadlines and time_to_minutes(act["end_time"]) > time_to_minutes(meal_deadlines[atype]):
                        act["_skip_meal"] = True
                        continue

                current_pos = position
                current_time = add_minutes(act["end_time"], 10)
            except RuntimeError:
                current_pos = position
        else:
            try:
                act["start_time"] = current_time
                act["end_time"] = add_minutes(current_time, _activity_duration(act))
                current_time = add_minutes(act["end_time"], 10)
            except RuntimeError:
                pass
    return current_pos


def _initial_day_time(activities: list[dict[str, Any]]) -> str:
    """返回当天起点时间。城际到达后从 end_time+buffer 开始，不可从出发时间开始。"""
    if not activities:
        return "08:00"
    if activities[0].get("type") in {"airplane", "train"}:
        # Bug fix 1.1: 使用到达时间而非出发时间
        raw_end = activities[0].get("end_time", "10:30")
        try:
            return add_minutes(raw_end, 30)
        except RuntimeError:
            return "10:30"
    return "09:00"


def _normalize_intercity_station(value: str, mode: str) -> str:
    """规范城际站点名：若已是完整站名则原样保留，仅城市名补默认后缀。

    >>> _normalize_intercity_station('Chengdu East Railway Station', 'train')
    'Chengdu East Railway Station'
    >>> _normalize_intercity_station('Chengdu', 'train')
    'Chengdu Railway Station'
    """
    if not value:
        return ""
    v = value.strip()
    # 已含站点/机场关键词 → 原样返回
    station_keywords = ("station", "airport", "railway", "车站", "机场", "火车站")
    if any(k in v.lower() for k in station_keywords):
        return v
    # 仅城市名 → 补默认后缀
    if mode == "airplane":
        return f"{v} Airport"
    if mode == "train":
        return f"{v} Railway Station"
    return v


def _intercity_arrival_station(act: dict[str, Any]) -> str:
    """城际到达站点名（使用 normalize 避免重复拼接）。"""
    end = act.get("end", "")
    atype = act.get("type", "")
    return _normalize_intercity_station(end, atype) if end else ""


def _intercity_departure_station(act: dict[str, Any]) -> str:
    """城际出发站点名。"""
    start = act.get("start", "")
    atype = act.get("type", "")
    return _normalize_intercity_station(start, atype) if start else ""


def _overnight_position(activities: list[dict[str, Any]]) -> str:
    for act in reversed(activities):
        if act.get("type") == "accommodation" and act.get("position"):
            return str(act["position"])
    return ""


def _activity_duration(act: dict[str, Any]) -> int:
    try:
        start = time_to_minutes(act.get("start_time", "00:00"))
        end = time_to_minutes(act.get("end_time", "00:45"))
        return max(30, end - start)
    except Exception:
        return 60
