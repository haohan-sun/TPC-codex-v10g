"""Lightweight local checker before official/schema verification.

Phase 5: Added checks for breakfast presence, transport continuity,
free constraints, required attraction types, hard logic requirements.
"""
from __future__ import annotations

from src.data_layer.schema import Constraints, Plan
from src.planner.constraint_profile import extract_planning_constraints
from src.planner.plan_utils import time_to_minutes


def run_local_checker(plan: Plan, constraints: Constraints) -> Plan:
    pc = extract_planning_constraints(constraints)
    official = plan.metadata.get("official_plan") or {}
    itinerary = official.get("itinerary", [])
    issues: list[str] = []

    # ---- Schema ----
    for field in ("people_number", "start_city", "target_city", "itinerary"):
        if field not in official:
            issues.append(f"SCHEMA missing {field}")
    if official.get("people_number") != pc.people:
        issues.append(f"SCHEMA people_number={official.get('people_number')} expected={pc.people}")

    # ---- Per-day checks ----
    present_attractions: set[str] = set()
    present_types: set[str] = set()

    for day in itinerary:
        activities = day.get("activities", [])
        day_num = day.get("day", "?")
        types = {a.get("type") for a in activities}

        # breakfast: mandatory except day 1 late arrival
        if "breakfast" not in types:
            issues.append(f"MISSING_BREAKFAST day={day_num}")

        last_end = -1
        prev_position = ""
        prev_end_pos = ""

        for act in activities:
            atype = act.get("type", "")
            act_pos = str(act.get("position", ""))
            act_start = act.get("start_time", "")
            act_end = act.get("end_time", "")

            # Format
            for req in ("type", "start_time", "end_time", "cost", "price", "transports"):
                if req not in act:
                    issues.append(f"SCHEMA activity day={day_num} type={atype} missing {req}")

            # Time order
            try:
                start = time_to_minutes(act_start)
                end = time_to_minutes(act_end)
                if end <= start:
                    issues.append(f"TIME_ORDER day={day_num} {atype} end<={act_start} end={act_end}")
                if start < last_end:
                    issues.append(f"TIME_ORDER day={day_num} {atype} overlap prev_end={last_end}")
                last_end = max(last_end, end)
            except Exception:
                issues.append(f"TIME_ORDER invalid day={day_num} {atype}")

            # Transport continuity (skip intercity)
            if atype not in ("airplane", "train") and act_pos:
                transports = act.get("transports", []) or []
                if not transports and prev_position and prev_position != act_pos:
                    issues.append(f"TRANSPORT_CONTINUITY day={day_num} {atype}: no transport from {prev_position} to {act_pos}")
                if transports:
                    t_start = transports[0].get("start", "")
                    t_end = transports[-1].get("end", "")
                    if prev_end_pos and t_start != prev_end_pos and t_start != prev_position:
                        issues.append(f"TRANSPORT_CONTINUITY day={day_num} {atype}: transport.start={t_start} != prev.end={prev_end_pos}")
                    if t_end != act_pos:
                        issues.append(f"TRANSPORT_CONTINUITY day={day_num} {atype}: transport.end={t_end} != pos={act_pos}")
                    # Check transport time before activity
                    t_end_time = transports[-1].get("end_time", "")
                    if t_end_time and time_to_minutes(t_end_time) > time_to_minutes(act_start):
                        issues.append(f"TRANSPORT_CONTINUITY day={day_num} {atype}: transport.end_time={t_end_time} > activity.start={act_start}")

            # Activity type tracking
            if atype == "attraction":
                present_attractions.add(act_pos.lower())
                t = pc.must_visit_types  # alias
                meta = plan.metadata.get("poi_meta", {})
                poi_type = str((meta.get(act_pos, {}) or {}).get("type", "")).lower()
                if poi_type:
                    present_types.add(poi_type)

            # Tickets
            if atype in ("attraction", "airplane", "train"):
                tickets = act.get("tickets")
                if tickets is not None and tickets != pc.activity_tickets:
                    issues.append(f"TICKET day={day_num} {atype} tickets={tickets} expected={pc.activity_tickets}")

            # Transport price/cost
            for seg in act.get("transports") or []:
                mode = seg.get("mode", "")
                if mode == "metro" and seg.get("tickets") != pc.metro_tickets:
                    issues.append(f"TRANSPORT_INFO day={day_num} metro tickets={seg.get('tickets')} expected={pc.metro_tickets}")
                if mode == "taxi" and seg.get("cars") != pc.taxi_cars:
                    issues.append(f"TRANSPORT_INFO day={day_num} taxi cars={seg.get('cars')} expected={pc.taxi_cars}")

            prev_position = act_pos
            if atype in ("airplane", "train"):
                prev_end_pos = str(act.get("end", act.get("start", act_pos)))
            else:
                prev_end_pos = act_pos

    # ---- Must-visit constraints ----
    for name in pc.must_visit:
        if not any(name.lower() in p for p in present_attractions):
            issues.append(f"HARD_LOGIC_MISSING_ATTRACTION must_visit={name}")
    for atype in pc.must_visit_types:
        if not any(atype.lower() in t for t in present_types):
            issues.append(f"HARD_LOGIC_ATTRACTION_TYPE missing_type={atype}")

    # ---- Free constraints ----
    if pc.free_attraction:
        for day in itinerary:
            for act in day.get("activities", []):
                if act.get("type") == "attraction" and float(act.get("cost", 0)) > 0:
                    issues.append(f"HARD_LOGIC_BUDGET free_attraction: cost={act.get('cost')} at {act.get('position')}")

    # ---- Budget ----
    budget = plan.metadata.get("budget_report") or {}
    if budget.get("over_total") or budget.get("over_dining") or budget.get("over_accommodation"):
        issues.append(f"HARD_LOGIC_BUDGET {budget}")

    # ---- Count checks ----
    if len(itinerary) != pc.days:
        issues.append(f"SCHEMA days={len(itinerary)} expected={pc.days}")

    plan.metadata["local_check_issues"] = issues
    return plan
