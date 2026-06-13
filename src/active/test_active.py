"""active 模块独立测试。

运行方式（在 tpc_agent 目录下）::

    python src/active/test_active.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.active.active_query_selector import active_query_selector, get_last_active_info
from src.active.constraint_risk_estimator import estimate_constraint_risk
from src.active.uncertainty_analyzer import analyze_uncertainty
from src.constraints.constraint_parser import parse_constraints
from src.data_layer.database import TravelDatabase
from src.data_layer.loaders import load_query
from src.data_layer.paths import get_project_root


def _ok(name: str) -> None:
    print(f"  [PASS] {name}")


def test_uncertainty_and_risk() -> None:
    """测试不确定性分析与风险评估。"""
    sample = get_project_root() / "data" / "training data" / "20250324234255286741.json"
    if not sample.exists():
        print("  [SKIP] 无 training data")
        return

    query = load_query(sample)
    constraints = parse_constraints(query)

    uncertainty = analyze_uncertainty(constraints)
    assert uncertainty, "应产出不确定性分数"
    assert "budget" in uncertainty or "spatial" in uncertainty

    risk = estimate_constraint_risk(query, constraints)
    assert risk.query_id == query.query_id
    assert risk.risk_scores, "应产出风险分数"
    assert isinstance(risk.high_risk_categories, list)

    _ok(f"uncertainty={len(uncertainty)} 维, high_risk={risk.high_risk_categories[:3]}")


def test_active_query_with_sandbox() -> None:
    """使用临时沙盒测试主动数据拉取。"""
    sample = get_project_root() / "data" / "training data" / "20250324234255286741.json"
    if not sample.exists():
        print("  [SKIP] 无 training data")
        return

    query = load_query(sample)
    constraints = parse_constraints(query)
    risk = estimate_constraint_risk(query, constraints)

    with tempfile.TemporaryDirectory() as tmp:
        sandbox = Path(tmp)
        city = "Chengdu"

        # 写入景点
        (sandbox / "attractions").mkdir()
        pois = [
            {"id": "poi_east", "name": "East Lake Park", "latitude": 30.65, "longitude": 104.06, "price": 0},
            {"id": "poi_wide", "name": "Wide and Narrow Alley", "latitude": 30.66, "longitude": 104.05, "price": 0},
        ]
        with open(sandbox / "attractions" / f"{city}.json", "w", encoding="utf-8") as f:
            json.dump(pois, f)

        # 写入酒店
        (sandbox / "hotels").mkdir()
        hotels = [
            {
                "id": "hotel_1",
                "name": "Chengdu Free parking Hotel",
                "latitude": 30.651,
                "longitude": 104.061,
                "price": 300,
                "features": ["Free parking"],
            },
            {"id": "hotel_2", "name": "Budget Inn", "latitude": 30.70, "longitude": 104.10, "price": 800},
        ]
        with open(sandbox / "hotels" / f"{city}.json", "w", encoding="utf-8") as f:
            json.dump(hotels, f)

        # 写入餐厅
        (sandbox / "restaurants").mkdir()
        rests = [
            {"id": "rest_1", "name": "本地特色火锅", "price": 80, "cuisine": "Sichuan"},
        ]
        with open(sandbox / "restaurants" / f"{city}.json", "w", encoding="utf-8") as f:
            json.dump(rests, f)

        # 注入临时 sandbox 到 database
        db = TravelDatabase(sandbox_root=sandbox)
        import src.data_layer.database as db_module
        old_db = db_module._default_db
        db_module._default_db = db

        try:
            active_info = active_query_selector(constraints, risk)
            assert active_info.query_id == query.query_id
            assert active_info.priority_queries, "应生成优先查询列表"
            assert active_info.fetched_data.get("poi_count", 0) >= 1
            assert active_info.fetched_data.get("hotel_count", 0) >= 1
            assert "price_stats" in active_info.fetched_data

            cached = get_last_active_info()
            assert cached is active_info, "应缓存 active_info 供 candidates 使用"
            _ok(f"active_query_selector -> {len(active_info.priority_queries)} 条优先查询")
        finally:
            db_module._default_db = old_db


def test_main_flow_integration() -> None:
    """模拟 main.py 第 1~3 步。"""
    sample = get_project_root() / "data" / "training data" / "20250322220423800679.json"
    if not sample.exists():
        print("  [SKIP] 无 training data")
        return

    query = load_query(sample)
    constraints = parse_constraints(query)
    risk = estimate_constraint_risk(query, constraints)
    active_info = active_query_selector(constraints, risk)

    assert constraints.global_params.get("target_city")
    assert active_info.fetched_data.get("target_city") == constraints.global_params.get("target_city")
    _ok("main_flow: load_query -> parse_constraints -> estimate_risk -> active_query_selector")


def main() -> None:
    print("=" * 50)
    print("active 模块测试")
    print("=" * 50)

    test_uncertainty_and_risk()
    test_active_query_with_sandbox()
    test_main_flow_integration()

    print("=" * 50)
    print("全部 active 测试通过")
    print("=" * 50)


if __name__ == "__main__":
    main()
