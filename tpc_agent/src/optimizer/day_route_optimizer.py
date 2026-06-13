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
from src.optimizer.nearest_neighbor import nearest_neighbor_route
from src.optimizer.two_opt import two_opt
from src.planner.plan_utils import add_minutes, max_time, normalize_transports, time_to_minutes


MEAL_MIN_START = {"breakfast": "07:30", "lunch": "11:30", "dinner": "17:30"}


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
            )
            for slot, act in zip(attraction_slots, ordered):
                activities[slot] = act
        end_pos = _retime_day(activities, city, sandbox, plan, overnight_pos)
        overnight_pos = _overnight_position(activities) or end_pos

    plan.metadata["official_plan"] = official
    return plan


def _optimized_attraction_order(
    attraction_acts: list[dict[str, Any]],
    city: str,
    sandbox,
    poi_meta: dict[str, dict[str, Any]],
    start_anchor: str,
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
    greedy = _greedy_from_anchor(names, start_anchor, city, sandbox, poi_meta)
    optimized_names = two_opt(greedy, matrix)
    return [by_name[n] for n in optimized_names if n in by_name]


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
    if not a or not b or a == b:
        return 0.0
    try:
        dist = sandbox.poi_distance(city, a, b, "09:00", "metro")
        if dist is not None and dist > 0:
            return float(dist)
    except Exception:
        pass
    ca, cb = _coords(poi_meta.get(a, {})), _coords(poi_meta.get(b, {}))
    if ca and cb:
        import math

        r = 6371.0
        phi1, phi2 = math.radians(ca[0]), math.radians(cb[0])
        dphi = math.radians(cb[0] - ca[0])
        dlambda = math.radians(cb[1] - ca[1])
        x = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        return 2 * r * math.asin(math.sqrt(x))
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


def _retime_day(activities: list[dict[str, Any]], city: str, sandbox, plan: Plan, start_pos: str = "") -> str:
    """重排当天活动时间。城际交通保留原始真实时间，不篡改。"""
    current_time = _initial_day_time(activities)
    current_pos = start_pos
    pc = (plan.metadata.get("official_plan") or {}).get("_planning_constraints")
    people = getattr(pc, "people", 1)
    taxi_cars = getattr(pc, "taxi_cars", max(1, (people + 3) // 4))
    prefer_metro = getattr(pc, "prefer_metro", True)

    for act_idx, act in enumerate(activities):
        atype = act.get("type", "")

        if atype in ("airplane", "train"):
            # Bug fix 1.2: 城际交通保留原始真实时间
            # Bug fix 1.3: 返程前从当前位置到车站/机场添加市内交通
            station = _intercity_arrival_station(act) or act.get("end", "")
            intercity_depart = act.get("start_time", "")

            # 出发站在当前城市境内→这是返程；到达站在当前城市→这是到达
            is_return = bool(act.get("start"))  # 有 start 字段 = 城际 = 可能是返程

            if current_pos and station and current_pos != station and act_idx > 0:
                # 出发时间在当前活动时间之前→可能是次日车次，跳过 transport
                if intercity_depart and time_to_minutes(intercity_depart) < time_to_minutes(current_time):
                    # 次日发车：不做市内交通（旅行者应在夜间去车站）
                    pass
                else:
                    try:
                        mode = "taxi"
                        station_transports = sandbox.goto(
                            city, current_pos, station, current_time, mode,
                            people=people, taxi_cars=taxi_cars,
                        )
                        if station_transports:
                            act["transports"] = normalize_transports(station_transports, people, taxi_cars)
                    except Exception:
                        pass

            current_pos = station or current_pos
            # 到达时间作为后续起点（仅当这是到达而非返程）
            if not is_return:
                raw_end = act.get("end_time", current_time)
                try:
                    current_time = add_minutes(raw_end, 30)
                except RuntimeError:
                    current_time = max_time(current_time, raw_end)
            continue

        if atype in MEAL_MIN_START:
            current_time = max_time(current_time, MEAL_MIN_START[atype])
        if atype == "accommodation":
            current_time = max_time(current_time, "20:00")

        position = str(act.get("position", ""))
        if position:
            try:
                mode = "metro" if prefer_metro and atype != "accommodation" else "taxi"
                transports = sandbox.goto(city, current_pos, position, current_time, mode, people=people, taxi_cars=taxi_cars)
                act["transports"] = normalize_transports(transports, people, taxi_cars)
                arrive = act["transports"][-1]["end_time"] if act["transports"] else current_time
                act["start_time"] = act["transports"][0]["start_time"] if act["transports"] else current_time
                act["end_time"] = add_minutes(arrive, _activity_duration(act))
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


def _intercity_arrival_station(act: dict[str, Any]) -> str:
    """城际到达站点名。"""
    end = act.get("end", "")
    atype = act.get("type", "")
    if atype == "airplane":
        return f"{end} Airport" if end else ""
    if atype == "train":
        return f"{end} Railway Station" if end else ""
    return end


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
