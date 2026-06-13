"""Minimal tests for local travel-planning skills.

Run from project root:
    python src/skills/test_skills.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data_layer.schema import ConstraintCard, Constraints, ErrorType, POICandidate, TypedError
from src.skills.choose_hotel_anchor import choose_hotel_anchor_candidate
from src.skills.cross_city_day_light_plan import cross_city_day_light_plan
from src.skills.ground_travel_intent import ground_travel_intent
from src.skills.insert_meals import insert_meals_by_route
from src.skills.lock_must_visit import lock_must_visit_order
from src.skills.order_daily_route_with_meals import order_attraction_names
from src.skills.plan_selector_best_of_n import plan_selector_best_of_n
from src.skills.registry import list_skills
from src.skills.repair_by_typed_error import repair_by_typed_error


def _ok(name: str) -> None:
    print(f"  [PASS] {name}")


def test_registry() -> None:
    names = {s.name for s in list_skills()}
    expected = {
        "ground_travel_intent",
        "choose_hotel_anchor",
        "insert_meals_by_route",
        "lock_must_visit",
        "cross_city_day_light_plan",
        "order_daily_route_with_meals",
        "repair_by_typed_error",
        "plan_selector_best_of_n",
    }
    assert expected.issubset(names)
    _ok("registry contains 8 priority skills")


def test_ground_travel_intent() -> None:
    constraints = Constraints(
        query_id="q1",
        global_params={
            "nature_language": (
                "not too tired, hotel within 5 km of East Lake Park, "
                "want to visit park, do not visit Museum"
            )
        },
    )
    result = ground_travel_intent({"constraints": constraints})
    hints = result.decision["planning_hints"]
    assert hints["pace"] == "relaxed"
    assert "park" in hints["required_types"]
    assert "museum" in hints["avoid_types"]
    assert hints["hotel_max_distance_km"] == 5.0
    _ok("ground_travel_intent")


def test_choose_hotel_anchor() -> None:
    hotels = [
        POICandidate("h_far", "Far Hotel", metadata={"price": 100, "latitude": 30.0, "longitude": 104.0}),
        POICandidate("h_near", "Near Hotel", metadata={"price": 120, "latitude": 30.6501, "longitude": 104.0601}),
    ]
    pois = [
        POICandidate("p1", "East Lake Park", metadata={"latitude": 30.65, "longitude": 104.06}),
    ]
    pc = SimpleNamespace(
        target_city="Chengdu",
        hotel_near_anchor="East Lake Park",
        hotel_max_distance_km=2.0,
        accommodation_budget=None,
        required_hotel_type=None,
    )
    result = choose_hotel_anchor_candidate(hotels, pc, pois, policy="low_transport")
    assert result.decision["hotel_id"] == "h_near"
    _ok("choose_hotel_anchor")


def test_insert_meals_by_route() -> None:
    restaurants = [
        POICandidate("r1", "Cheap Noodles", metadata={"price": 20}),
        POICandidate("r2", "Lunch House", metadata={"price": 30}),
        POICandidate("r3", "Dinner House", metadata={"price": 40}),
    ]
    result = insert_meals_by_route({
        "day_activities": [],
        "restaurants": restaurants,
        "people": 2,
        "dining_budget": 300,
        "current_time": "09:00",
    })
    assert {p["type"] for p in result.patches} == {"breakfast", "lunch", "dinner"}
    _ok("insert_meals_by_route")


def test_lock_must_visit() -> None:
    pois = [
        POICandidate("p2", "Other Museum", metadata={"type": "museum"}),
        POICandidate("p1", "East Lake Park", metadata={"type": "park"}),
    ]
    result = lock_must_visit_order(pois, [], ["park"])
    assert result.decision["ordered_poi_ids"][0] == "p1"
    assert result.decision["locked_ids"] == ["p1"]
    _ok("lock_must_visit")


def test_cross_city_day_light_plan() -> None:
    result = cross_city_day_light_plan({"arrival_time": "20:34", "poi_count": 3})
    assert result.decision["light_day"] is True
    assert result.decision["allowed_pois"] == 0
    _ok("cross_city_day_light_plan")


def test_order_daily_route_with_meals() -> None:
    matrix = {
        ("Hotel", "B"): 1.0,
        ("Hotel", "C"): 5.0,
        ("B", "C"): 1.0,
        ("C", "B"): 1.0,
    }
    result = order_attraction_names(["C", "B"], matrix, "Hotel")
    assert result.decision["ordered_positions"][0] == "B"
    _ok("order_daily_route_with_meals")


def test_repair_by_typed_error() -> None:
    error = TypedError(ErrorType.MEAL, "missing lunch")
    result = repair_by_typed_error({"error": error})
    assert any(p["op"] == "insert_or_shift_meals" for p in result.patches)
    _ok("repair_by_typed_error")


def test_plan_selector_best_of_n() -> None:
    candidates = [
        ({"itinerary": []}, 100.0, "safe"),
        ({"itinerary": [{"day": 1, "activities": []}]}, 90.0, "budget"),
    ]
    result = plan_selector_best_of_n({"candidates": candidates})
    assert result.decision["selected_index"] == 1
    _ok("plan_selector_best_of_n")


def main() -> None:
    print("=" * 50)
    print("skills tests")
    print("=" * 50)
    test_registry()
    test_ground_travel_intent()
    test_choose_hotel_anchor()
    test_insert_meals_by_route()
    test_lock_must_visit()
    test_cross_city_day_light_plan()
    test_order_daily_route_with_meals()
    test_repair_by_typed_error()
    test_plan_selector_best_of_n()
    print("=" * 50)
    print("all skills tests passed")
    print("=" * 50)


if __name__ == "__main__":
    main()
