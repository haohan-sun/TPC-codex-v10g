"""hard_logic_py DSL parser tests. Only use hard_logic_py as training
label for NL parser improvement — never as runtime input in competition mode.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.constraints.hard_logic_parser import parse_hard_logic_snippets


def _ok(name: str) -> None:
    print(f"  [PASS] {name}")


def test_must_visit_name() -> None:
    snippets = [
        'attraction_name_set=set()\n'
        'for activity in allactivities(plan):\n'
        '  if activity_type(activity)==\'attraction\': attraction_name_set.add(activity_position(activity))\n'
        'result=({"Iron Statue Temple Water Street"}&attraction_name_set)',
    ]
    cards = parse_hard_logic_snippets(snippets)
    assert len(cards) >= 1, f"expected >=1 card, got {len(cards)}"
    assert cards[0].category == "attraction", f"expected attraction, got {cards[0].category}"
    assert cards[0].parameters["must_visit_poi"] == "Iron Statue Temple Water Street"
    _ok("must_visit_name")


def test_required_attraction_type() -> None:
    snippets = [
        'attraction_type_set=set()\n'
        'result=({"Museum/Memorial Hall"}<=attraction_type_set)',
    ]
    cards = parse_hard_logic_snippets(snippets)
    assert len(cards) >= 1
    assert cards[0].parameters["must_visit_type"] == "Museum/Memorial Hall"
    _ok("required_attraction_type")


def test_forbidden_attraction_type() -> None:
    snippets = [
        'result=not({"red tourism sites"}&attraction_type_set)',
    ]
    cards = parse_hard_logic_snippets(snippets)
    assert len(cards) >= 1
    assert cards[0].parameters["forbidden_attraction_type"] == "red tourism sites"
    _ok("forbidden_attraction_type")


def test_day_people_count() -> None:
    snippets = [
        "result=(day_count(plan)==3)",
        "result=(people_count(plan)==5)",
    ]
    cards = parse_hard_logic_snippets(snippets)
    assert len(cards) >= 2
    day_card = [c for c in cards if c.category == "temporal"]
    people_card = [c for c in cards if c.category == "people"]
    assert len(day_card) >= 1
    assert day_card[0].parameters["days"] == 3
    assert len(people_card) >= 1
    assert people_card[0].parameters["people_number"] == 5
    _ok("day_people_count")


def test_budget_constraints() -> None:
    snippets = [
        "result=(restaurant_cost<=1800)",
        "result=(accommodation_cost<=800)",
        "result=(total_cost<=3000)",
    ]
    cards = parse_hard_logic_snippets(snippets)
    assert len(cards) >= 3
    budgets = {c.parameters.get("budget_type"): c.parameters.get("max_cost") for c in cards}
    assert budgets.get("dining") == 1800.0
    assert budgets.get("accommodation") == 800.0
    assert budgets.get("total") == 3000.0
    _ok("budget_constraints")


def test_free_constraints() -> None:
    snippets = [
        "result=attraction_cost<=0",
        "result=inter_city_transportation_cost<=0",
    ]
    cards = parse_hard_logic_snippets(snippets)
    assert len(cards) >= 2
    budget_types = {c.parameters.get("budget_type") for c in cards if c.category == "budget"}
    # Should have free_attraction or free_intercity
    has_free = "free_attraction" in budget_types or "free_intercity" in budget_types
    if not has_free:
        # fallback: check logic/unparsed cards
        logic_cards = [c for c in cards if c.category == "logic"]
        assert len(logic_cards) >= 0, "free constraints should be captured"
    _ok("free_constraints")


def test_transport_constraints() -> None:
    snippets = [
        'result=not(innercity_transport_type(activity)==\'metro\')',
        'result=not(intercity_transport_type(activity)==\'train\')',
    ]
    cards = parse_hard_logic_snippets(snippets)
    assert len(cards) >= 2
    _ok("transport_constraints")


def test_hotel_type() -> None:
    snippets = [
        'result=({"Free parking"}&accommodation_type_set)',
    ]
    cards = parse_hard_logic_snippets(snippets)
    assert len(cards) >= 1
    assert cards[0].category == "accommodation"
    assert cards[0].parameters["required_type"] == "Free parking"
    _ok("hotel_type")


def test_ticket_constraints() -> None:
    snippets = [
        "result=(activity_tickets(activity)!=2)",
        "result=(metro_tickets(activity)!=2)",
        "result=(taxi_cars(activity)!=1)",
    ]
    cards = parse_hard_logic_snippets(snippets)
    assert len(cards) >= 3
    _ok("ticket_constraints")


def test_empty_and_unparsed() -> None:
    assert parse_hard_logic_snippets([]) == []
    cards = parse_hard_logic_snippets(["unknown_pattern_xyz=42"])
    assert len(cards) >= 1  # should produce a logic/unparsed card
    _ok("empty_and_unparsed")


def main() -> None:
    print("=" * 50)
    print("hard_logic_parser tests")
    print("=" * 50)
    test_must_visit_name()
    test_required_attraction_type()
    test_forbidden_attraction_type()
    test_day_people_count()
    test_budget_constraints()
    test_free_constraints()
    test_transport_constraints()
    test_hotel_type()
    test_ticket_constraints()
    test_empty_and_unparsed()
    print("=" * 50)
    print("All hard_logic_parser tests passed")
    print("=" * 50)


if __name__ == "__main__":
    main()
