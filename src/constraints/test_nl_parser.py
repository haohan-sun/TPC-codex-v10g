"""NL Parser unit tests — 覆盖所有模糊约束映射。"""

from __future__ import annotations

import sys
from pathlib import Path

# 项目根目录加入 path
_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.constraints.nl_parser import parse_nature_language

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _cards_by_category(cards, category: str) -> list:
    return [c for c in cards if c.category == category]


def _any_description_contains(cards, keyword: str) -> bool:
    return any(keyword.lower() in c.description.lower() for c in cards)


def _param_value(cards, category: str, param: str):
    for c in cards:
        if c.category == category and param in c.parameters:
            return c.parameters[param]
    return None


# ===================================================================
# Pace / Energy
# ===================================================================


def test_relaxed_pace_en():
    cards = parse_nature_language("I want a relaxed trip, not too tired")
    assert _any_description_contains(cards, "Relaxed pace")
    assert _param_value(cards, "preference", "pace") == "relaxed"


def test_relaxed_pace_zh():
    cards = parse_nature_language("轻松一点，不要太累")
    assert _param_value(cards, "preference", "pace") == "relaxed"


def test_intensive_pace_en():
    cards = parse_nature_language("Visit as many as possible, packed schedule")
    assert _param_value(cards, "preference", "pace") == "intensive"


def test_intensive_pace_zh():
    cards = parse_nature_language("尽量多去几个景点，排满")
    assert _param_value(cards, "preference", "pace") == "intensive"


def test_no_pace_default():
    cards = parse_nature_language("Visit Beijing and Shanghai")
    pace_cards = _cards_by_category(cards, "preference")
    has_pace = any(c.parameters.get("pace") for c in pace_cards)
    assert not has_pace


# ===================================================================
# Budget
# ===================================================================


def test_dining_budget_en():
    cards = parse_nature_language("Dining budget is 200 per day")
    b = _cards_by_category(cards, "budget")
    assert any(c.parameters.get("budget_type") == "dining" and c.parameters.get("max_cost") == 200 for c in b)


def test_accommodation_budget_en():
    cards = parse_nature_language("Hotel budget below 500")
    b = _cards_by_category(cards, "budget")
    assert any(c.parameters.get("budget_type") == "accommodation" and c.parameters.get("max_cost") == 500 for c in b)


def test_total_budget_en():
    cards = parse_nature_language("Total budget no more than 3000")
    b = _cards_by_category(cards, "budget")
    assert any(c.parameters.get("budget_type") == "total" and c.parameters.get("max_cost") == 3000 for c in b)


def test_total_budget_zh():
    cards = parse_nature_language("预算不超过5000")
    b = _cards_by_category(cards, "budget")
    assert any(c.parameters.get("max_cost") == 5000 for c in b)


def test_multiple_budgets():
    cards = parse_nature_language("Dining budget 200, accommodation budget 600")
    b = _cards_by_category(cards, "budget")
    assert len(b) >= 2


# ===================================================================
# Hotel spatial
# ===================================================================


def test_hotel_within_distance():
    cards = parse_nature_language("Hotel should be within 5 km of West Lake")
    spatial = _cards_by_category(cards, "spatial")
    assert len(spatial) >= 1
    assert spatial[0].parameters.get("max_distance_km") == 5
    assert "West Lake" in spatial[0].parameters.get("anchor_poi", "")


def test_hotel_near_zh():
    cards = parse_nature_language("住宿在故宫附近3公里以内")
    spatial = _cards_by_category(cards, "spatial")
    assert len(spatial) >= 1


def test_hotel_free_parking():
    cards = parse_nature_language("Hotel must have free parking")
    acc = _cards_by_category(cards, "accommodation")
    assert any("Free parking" in str(c.parameters.get("required_type", "")) for c in acc)


def test_hotel_wifi():
    cards = parse_nature_language("Need a hotel with wifi")
    acc = _cards_by_category(cards, "accommodation")
    assert any("WiFi" in str(c.parameters.get("required_type", "")) for c in acc)


def test_hotel_name_list():
    cards = parse_nature_language(
        "We hope to stay at one of the following hotels: "
        "Four Points by Sheraton Shanghai Kangqiao or Atour S hotel, Shanghai Wanyuan Road."
    )
    acc = _cards_by_category(cards, "accommodation")
    names = [c.parameters.get("required_name") for c in acc]
    assert "Four Points by Sheraton Shanghai Kangqiao" in names
    assert "Atour S hotel, Shanghai Wanyuan Road" in names


def test_hotel_instagrammable_pool_and_sauna():
    pool = _cards_by_category(parse_nature_language("Need a hotel with an Instagrammable swimming pool"), "accommodation")
    sauna = _cards_by_category(parse_nature_language("Prefer to stay at a Sauna-type hotel"), "accommodation")
    assert any(c.parameters.get("required_type") == "Instagrammable swimming pool" for c in pool)
    assert any(c.parameters.get("required_type") == "Sauna" for c in sauna)


# ===================================================================
# Forbidden / must-visit
# ===================================================================


def test_do_not_visit_type():
    cards = parse_nature_language("Do not visit museums")
    att = _cards_by_category(cards, "attraction")
    assert any("museum" in str(c.parameters.get("forbidden_attraction_type", "")).lower() for c in att)


def test_avoid_type():
    cards = parse_nature_language("Avoid amusement parks and zoos")
    att = _cards_by_category(cards, "attraction")
    assert len(att) >= 1


def test_must_visit_type():
    cards = parse_nature_language("Must visit historical sites")
    att = _cards_by_category(cards, "attraction")
    assert any("historical site" in str(c.parameters.get("must_visit_type", "")).lower() for c in att)


def test_must_visit_poi():
    cards = parse_nature_language("We want to visit the Forbidden City and the Great Wall")
    att = _cards_by_category(cards, "attraction")
    must_pois = [c for c in att if c.parameters.get("must_visit_poi")]
    assert len(must_pois) >= 1


def test_named_park_is_poi_not_type():
    cards = parse_nature_language("Wish to visit Zhongshan Park.")
    att = _cards_by_category(cards, "attraction")
    assert any(c.parameters.get("must_visit_poi") == "Zhongshan Park" for c in att)
    assert not any(c.parameters.get("must_visit_type") == "Zhongshan Park" for c in att)


def test_visit_name_with_no_period():
    cards = parse_nature_language("Hope to visit Exploration Capsule: Cloudtop Playland. The budget is 1700.")
    att = _cards_by_category(cards, "attraction")
    assert any(c.parameters.get("must_visit_poi") == "Exploration Capsule: Cloudtop Playland" for c in att)


def test_multi_poi_with_abbreviation_period():
    cards = parse_nature_language(
        "We want to visit Lujiazui, Fly Over Shanghai (No. 1 Department Store), and Changle Road. "
        "We do not want to stay in hotels that have a Sunbathing area."
    )
    att = _cards_by_category(cards, "attraction")
    names = [c.parameters.get("must_visit_poi") for c in att]
    assert "Lujiazui" in names
    assert "Fly Over Shanghai (No. 1 Department Store)" in names
    assert "Changle Road" in names


def test_forbidden_poi():
    cards = parse_nature_language("Do not visit Disneyland")
    att = _cards_by_category(cards, "attraction")
    assert any(c.parameters.get("forbidden_poi") for c in att)


def test_forbidden_zh():
    cards = parse_nature_language("不想去博物馆")
    att = _cards_by_category(cards, "attraction")
    assert len(att) >= 1


# ===================================================================
# Cuisine / dining
# ===================================================================


def test_local_cuisine():
    cards = parse_nature_language("I want to try local food")
    diet = _cards_by_category(cards, "dietary")
    assert any("local" in str(c.parameters.get("cuisine_preference", "")).lower() for c in diet)


def test_sichuan_cuisine():
    cards = parse_nature_language("Must eat Sichuan cuisine")
    diet = _cards_by_category(cards, "dietary")
    assert any("Sichuan" in str(c.parameters.get("cuisine_preference", "")) for c in diet)


def test_hotpot():
    cards = parse_nature_language("I want hotpot for dinner")
    diet = _cards_by_category(cards, "dietary")
    assert any("hotpot" in str(c.parameters.get("cuisine_preference", "")).lower() for c in diet)


def test_hot_pot_spaced():
    cards = parse_nature_language("Want to try one of the following restaurant types: Hot pot.")
    diet = _cards_by_category(cards, "dietary")
    assert any("hotpot" in str(c.parameters.get("cuisine_preference", "")).lower() for c in diet)


def test_restaurant_name_list():
    cards = parse_nature_language(
        "Want to try the following restaurants: Lotus Restaurant, Haling Noodle House, "
        "and Shanghai Center J Hotel Sky Silk Chinese Restaurant."
    )
    diet = _cards_by_category(cards, "dietary")
    names = [c.parameters.get("restaurant_name") for c in diet]
    assert "Lotus Restaurant" in names
    assert "Haling Noodle House" in names
    assert "Shanghai Center J Hotel Sky Silk Chinese Restaurant" in names


def test_forbidden_restaurant_name_not_positive():
    cards = parse_nature_language("Do not want to try the following restaurant: Lu's Soup Dumpling King.")
    diet = _cards_by_category(cards, "dietary")
    assert not any(c.parameters.get("restaurant_name") for c in diet)


def test_cantonese():
    cards = parse_nature_language("Try Cantonese cuisine")
    diet = _cards_by_category(cards, "dietary")
    assert any("Cantonese" in str(c.parameters.get("cuisine_preference", "")) for c in diet)


# ===================================================================
# Transport
# ===================================================================


def test_train_preference():
    cards = parse_nature_language("I prefer to go by train")
    t = _cards_by_category(cards, "transport")
    assert any(c.parameters.get("intercity_mode") == "train" for c in t)


def test_airplane_preference():
    cards = parse_nature_language("Take a flight to Shanghai")
    t = _cards_by_category(cards, "transport")
    assert any(c.parameters.get("intercity_mode") == "airplane" for c in t)


def test_metro_preference():
    cards = parse_nature_language("Use metro for getting around in the city")
    t = _cards_by_category(cards, "transport")
    assert any(c.parameters.get("innercity_mode") == "metro" for c in t)


def test_taxi_preference():
    cards = parse_nature_language("We will use taxi")
    t = _cards_by_category(cards, "transport")
    assert any(c.parameters.get("innercity_mode") == "taxi" for c in t)


# ===================================================================
# Combined / edge cases
# ===================================================================


def test_combined_budget_and_pace():
    cards = parse_nature_language("relaxed trip with dining budget 300")
    assert _param_value(cards, "preference", "pace") == "relaxed"
    b = _cards_by_category(cards, "budget")
    assert any(c.parameters.get("budget_type") == "dining" for c in b)


def test_empty_query():
    cards = parse_nature_language("")
    assert cards == []


def test_whitespace_query():
    cards = parse_nature_language("   ")
    assert cards == []


def test_no_constraints():
    cards = parse_nature_language("Hello world, just a random sentence")
    # Should not crash, maybe a few cards or empty
    assert isinstance(cards, list)


def test_mixed_en_zh():
    cards = parse_nature_language("预算3000, take train, 轻松 pace")
    assert _param_value(cards, "preference", "pace") == "relaxed"
    assert any(c.parameters.get("intercity_mode") == "train" for c in _cards_by_category(cards, "transport"))
    assert any(c.parameters.get("max_cost") == 3000 for c in _cards_by_category(cards, "budget"))


# ===================================================================
# Main
# ===================================================================


def main() -> None:
    tests = [
        # pace
        ("relaxed_pace_en", test_relaxed_pace_en),
        ("relaxed_pace_zh", test_relaxed_pace_zh),
        ("intensive_pace_en", test_intensive_pace_en),
        ("intensive_pace_zh", test_intensive_pace_zh),
        ("no_pace_default", test_no_pace_default),
        # budget
        ("dining_budget_en", test_dining_budget_en),
        ("accommodation_budget_en", test_accommodation_budget_en),
        ("total_budget_en", test_total_budget_en),
        ("total_budget_zh", test_total_budget_zh),
        ("multiple_budgets", test_multiple_budgets),
        # hotel
        ("hotel_within_distance", test_hotel_within_distance),
        ("hotel_near_zh", test_hotel_near_zh),
        ("hotel_free_parking", test_hotel_free_parking),
        ("hotel_wifi", test_hotel_wifi),
        ("hotel_name_list", test_hotel_name_list),
        ("hotel_instagrammable_pool_and_sauna", test_hotel_instagrammable_pool_and_sauna),
        # forbidden/must-visit
        ("do_not_visit_type", test_do_not_visit_type),
        ("avoid_type", test_avoid_type),
        ("must_visit_type", test_must_visit_type),
        ("must_visit_poi", test_must_visit_poi),
        ("named_park_is_poi_not_type", test_named_park_is_poi_not_type),
        ("visit_name_with_no_period", test_visit_name_with_no_period),
        ("multi_poi_with_abbreviation_period", test_multi_poi_with_abbreviation_period),
        ("forbidden_poi", test_forbidden_poi),
        ("forbidden_zh", test_forbidden_zh),
        # cuisine
        ("local_cuisine", test_local_cuisine),
        ("sichuan_cuisine", test_sichuan_cuisine),
        ("hotpot", test_hotpot),
        ("hot_pot_spaced", test_hot_pot_spaced),
        ("restaurant_name_list", test_restaurant_name_list),
        ("forbidden_restaurant_name_not_positive", test_forbidden_restaurant_name_not_positive),
        ("cantonese", test_cantonese),
        # transport
        ("train_preference", test_train_preference),
        ("airplane_preference", test_airplane_preference),
        ("metro_preference", test_metro_preference),
        ("taxi_preference", test_taxi_preference),
        # combined
        ("combined_budget_and_pace", test_combined_budget_and_pace),
        ("empty_query", test_empty_query),
        ("whitespace_query", test_whitespace_query),
        ("no_constraints", test_no_constraints),
        ("mixed_en_zh", test_mixed_en_zh),
    ]

    passed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  [PASS] {name}")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")

    print(f"\n{'=' * 50}")
    print(f"NL Parser: {passed}/{len(tests)} 通过")
    if passed < len(tests):
        sys.exit(1)


if __name__ == "__main__":
    main()
