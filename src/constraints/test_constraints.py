"""constraints 模块独立测试。

运行方式（在 tpc_agent 目录下）::

    python src/constraints/test_constraints.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.constraints.constraint_card import build_constraint_card, merge_cards
from src.constraints.constraint_parser import parse_constraints
from src.constraints.constraint_validator import validate_constraints
from src.constraints.hard_logic_parser import parse_hard_logic_snippets
from src.data_layer.loaders import load_query
from src.data_layer.paths import get_project_root


def _ok(name: str) -> None:
    print(f"  [PASS] {name}")


def test_build_and_merge_cards() -> None:
    """测试卡片构建与去重。"""
    c1 = build_constraint_card(
        category="temporal",
        description="3天",
        parameters={"days": 3},
        card_id="meta_days",
    )
    c2 = build_constraint_card(
        category="temporal",
        description="3天行程",
        parameters={"days": 3},
        card_id="hard_days",
    )
    merged = merge_cards([c1, c2])
    assert len(merged) == 1, "相同 days 硬约束应合并为 1 张"
    _ok("merge_cards")


def test_hard_logic_parser() -> None:
    """测试 DSL 解析。"""
    snippets = [
        "restaurant_cost=0\nfor activity in allactivities(plan):\n  if activity_type(activity) in ['breakfast', 'lunch', 'dinner']: restaurant_cost+=activity_cost(activity)\nresult=restaurant_cost<=1800",
        "result=(day_count(plan)==3)",
        "result=(people_count(plan)==5)",
    ]
    cards = parse_hard_logic_snippets(snippets)
    categories = {c.category for c in cards}
    assert "budget" in categories
    assert "temporal" in categories
    assert "people" in categories
    _ok("hard_logic_parser")


def test_parse_constraints_from_training_sample() -> None:
    """使用真实 training data 测试完整约束解析。"""
    training_dir = get_project_root() / "data" / "training data"
    sample = training_dir / "20250324234255286741.json"
    if not sample.exists():
        print("  [SKIP] 未找到样例 query 文件")
        return

    query = load_query(sample)
    constraints = parse_constraints(query)

    assert constraints.query_id == query.query_id
    assert constraints.global_params["target_city"] == "Chengdu"
    assert constraints.global_params["days"] == 3
    assert constraints.global_params["people_number"] == 5
    assert len(constraints.cards) >= 4, "应解析出多条约束卡片"

    categories = {c.category for c in constraints.cards}
    assert "budget" in categories, "应包含餐饮预算约束"
    assert "spatial" in categories, "应包含空间/城市约束"

    # 检查餐饮预算卡片
    dining = [
        c for c in constraints.cards
        if c.category == "budget" and c.parameters.get("budget_type") == "dining"
    ]
    assert dining and dining[0].parameters.get("max_cost") == 1800.0

    _ok(f"parse_constraints -> {len(constraints.cards)} 张卡片, categories={categories}")


def test_validator_detects_missing_fields() -> None:
    """测试校验器能发现缺失字段。"""
    from src.data_layer.schema import Constraints

    bad = Constraints(query_id="x", cards=[], global_params={})
    issues = validate_constraints(bad)
    assert any("start_city" in i for i in issues)
    assert any("target_city" in i for i in issues)
    _ok("validate_constraints")


def test_main_flow_integration() -> None:
    """模拟 main.py 前两步：load_query + parse_constraints。"""
    training_dir = get_project_root() / "data" / "training data"
    if not training_dir.exists():
        print("  [SKIP] 无 training data")
        return

    query = load_query(training_dir / "20250322220423800679.json")
    constraints = parse_constraints(query)

    # main.py 会把 constraints 传给 estimate_constraint_risk / build_candidates 等
    assert constraints.query_id == query.query_id
    assert "start_city" in constraints.global_params
    assert isinstance(constraints.cards, list)
    _ok("main_flow_integration (load_query -> parse_constraints)")


def main() -> None:
    print("=" * 50)
    print("constraints 测试")
    print("=" * 50)

    test_build_and_merge_cards()
    test_hard_logic_parser()
    test_validator_detects_missing_fields()
    test_parse_constraints_from_training_sample()
    test_main_flow_integration()

    print("=" * 50)
    print("全部 constraints 测试通过")
    print("=" * 50)


if __name__ == "__main__":
    main()
