"""candidates 模块独立测试。

运行方式（在 tpc_agent 目录下）::

    python src/candidates/test_candidates.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.active.active_query_selector import active_query_selector
from src.active.constraint_risk_estimator import estimate_constraint_risk
from src.candidates.candidate_generator import build_candidates
from src.candidates.hotel_ranker import rank_hotels
from src.candidates.poi_ranker import rank_pois
from src.candidates.restaurant_ranker import rank_restaurants
from src.candidates.transport_ranker import rank_transports
from src.constraints.constraint_parser import parse_constraints
from src.data_layer.database import TravelDatabase
from src.data_layer.loaders import load_query
from src.data_layer.paths import get_project_root
from src.data_layer.schema import GroundedPreferences


def _ok(name: str) -> None:
    print(f"  [PASS] {name}")


def _mock_preferences(query_id: str) -> GroundedPreferences:
    """构造测试用偏好权重（模拟 semantic_grounding 输出）。"""
    return GroundedPreferences(
        query_id=query_id,
        poi_weights={"East Lake Park": 2.0, "Wide and Narrow Alley": 1.0},
        cuisine_weights={"local": 1.5, "Sichuan": 1.0},
        pace_weight=0.4,
        transport_weight=0.5,
        budget_weight=0.8,
        tags={"cuisine_preference": "local"},
    )


def test_rankers_unit() -> None:
    """单元测试各排序器。"""
    prefs = _mock_preferences("test")
    pois = [
        {"id": "p1", "name": "East Lake Park", "price": 0, "region": "A"},
        {"id": "p2", "name": "Wide and Narrow Alley", "price": 0, "region": "B"},
        {"id": "p3", "name": "Other Spot", "price": 10, "region": "A"},
    ]
    ranked = rank_pois(pois, prefs, top_k=2, must_visit_ids={"p1"})
    assert len(ranked) == 2
    assert ranked[0].poi_id == "p1", "必去 POI 应排第一"

    hotels = [
        {"id": "h1", "name": "Free parking Hotel", "price": 300, "features": ["Free parking"],
         "latitude": 30.651, "longitude": 104.061},
        {"id": "h2", "name": "Expensive", "price": 5000},
    ]
    from src.data_layer.schema import Constraints
    constraints = Constraints(
        query_id="t",
        global_params={"days": 3, "people_number": 2},
        cards=[],
    )
    from src.constraints.constraint_card import build_constraint_card
    constraints.cards.append(
        build_constraint_card("budget", "住宿预算", {"budget_type": "accommodation", "max_cost": 1000})
    )
    hotel_ranked = rank_hotels(hotels, constraints, top_k=5)
    assert len(hotel_ranked) == 1 and hotel_ranked[0].poi_id == "h1"

    rests = rank_restaurants(
        [{"id": "r1", "name": "本地特色餐厅", "price": 60, "cuisine": "Sichuan"}],
        prefs,
        constraints=constraints,
        top_k=5,
    )
    assert len(rests) == 1

    transports = rank_transports(
        [{"mode": "airplane"}, {"mode": "train"}],
        constraints,
    )
    assert len(transports) >= 2
    _ok("rankers_unit")


def test_build_candidates_with_sandbox() -> None:
    """端到端测试候选池构建。"""
    sample = get_project_root() / "data" / "training data" / "20250324234255286741.json"
    if not sample.exists():
        print("  [SKIP] 无 training data")
        return

    query = load_query(sample)
    constraints = parse_constraints(query)
    risk = estimate_constraint_risk(query, constraints)
    prefs = _mock_preferences(query.query_id)

    with tempfile.TemporaryDirectory() as tmp:
        sandbox = Path(tmp)
        city = "Chengdu"

        for folder, fname, data in [
            ("attractions", f"{city}.json", [
                {"id": "poi_east", "name": "East Lake Park", "latitude": 30.65, "longitude": 104.06, "price": 0, "region": "A"},
                {"id": "poi_wide", "name": "Wide and Narrow Alley", "latitude": 30.66, "longitude": 104.05, "price": 0, "region": "B"},
            ]),
            ("hotels", f"{city}.json", [
                {"id": "h1", "name": "Near East Lake Free parking Hotel", "price": 250,
                 "latitude": 30.651, "longitude": 104.061, "features": ["Free parking"]},
            ]),
            ("restaurants", f"{city}.json", [
                {"id": "r1", "name": "本地特色火锅", "price": 80, "cuisine": "Sichuan"},
            ]),
        ]:
            (sandbox / folder).mkdir()
            with open(sandbox / folder / fname, "w", encoding="utf-8") as f:
                json.dump(data, f)

        import src.data_layer.database as db_module
        old_db = db_module._default_db
        db_module._default_db = TravelDatabase(sandbox_root=sandbox)

        try:
            # 先跑 active（模拟 main.py），再 build_candidates
            active_query_selector(constraints, risk)
            pool = build_candidates(constraints, prefs)

            assert pool.query_id == query.query_id
            assert len(pool.pois) >= 1, "应有景点候选"
            assert len(pool.hotels) >= 1, "应有酒店候选"
            assert len(pool.restaurants) >= 1, "应有餐厅候选"
            assert len(pool.transports) >= 1, "应有交通选项"

            # 必去/高权重 POI 应排在前列
            poi_ids = [p.poi_id for p in pool.pois]
            assert "poi_east" in poi_ids

            _ok(
                f"build_candidates -> pois={len(pool.pois)}, "
                f"hotels={len(pool.hotels)}, restaurants={len(pool.restaurants)}"
            )
        finally:
            db_module._default_db = old_db


def test_main_flow_steps_1_to_5() -> None:
    """模拟 main.py 前 5 步（semantic 用 mock preferences 替代）。"""
    sample = get_project_root() / "data" / "training data" / "20250322220423800679.json"
    if not sample.exists():
        print("  [SKIP] 无 training data")
        return

    query = load_query(sample)
    constraints = parse_constraints(query)
    risk = estimate_constraint_risk(query, constraints)
    active_info = active_query_selector(constraints, risk)
    preferences = _mock_preferences(query.query_id)
    pool = build_candidates(constraints, preferences)

    assert pool.query_id == query.query_id
    assert active_info.fetched_data.get("transports"), "active 应拉取交通选项"
    _ok("main_flow steps 1-5 (through build_candidates)")


def main() -> None:
    print("=" * 50)
    print("candidates 模块测试")
    print("=" * 50)

    test_rankers_unit()
    test_build_candidates_with_sandbox()
    test_main_flow_steps_1_to_5()

    print("=" * 50)
    print("全部 candidates 测试通过")
    print("=" * 50)


if __name__ == "__main__":
    main()
