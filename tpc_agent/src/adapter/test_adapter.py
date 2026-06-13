"""官方 Agent 适配层独立测试。

运行::

    python src/adapter/test_adapter.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.adapter.plan_formatter import build_empty_plan, format_official_plan, is_plan_success
from src.adapter.query_adapter import prepare_official_query
from src.adapter.runner import run_single_official_query
from tpc_agent import TPCAgent


def _ok(name: str) -> None:
    print(f"  [PASS] {name}")


def test_query_adapter_strips_oracle() -> None:
    """正式模式应剥离 hard_logic_py。"""
    raw = {
        "uid": "test_001",
        "nature_language": "去成都玩3天",
        "hard_logic_py": ["result=True"],
        "people_number": 2,
        "start_city": "上海",
        "target_city": "成都",
    }
    q = prepare_official_query(raw, oracle_translation=False)
    assert "hard_logic_py" not in q.metadata
    assert q.query_id == "test_001"
    assert "成都" in q.raw_text
    _ok("query_adapter strips oracle")


def test_plan_formatter_empty() -> None:
    """空 plan 应符合官方顶层字段。"""
    query = {"people_number": 5, "start_city": "Suzhou", "target_city": "Chengdu"}
    plan = build_empty_plan(query, elapsed_sec=1.23)
    assert plan["people_number"] == 5
    assert plan["start_city"] == "Suzhou"
    assert plan["itinerary"] == []
    assert not is_plan_success(plan)
    _ok("plan_formatter empty")


def test_plan_formatter_from_pipeline() -> None:
    """pipeline 返回 day 列表时应包装为官方结构。"""
    query = {"people_number": 1, "start_city": "A", "target_city": "B"}
    result = {"query_id": "x", "score": 0.5, "itinerary": [{"day": 1, "activities": []}]}
    plan = format_official_plan(query, result, elapsed_sec=2.0)
    assert plan["target_city"] == "B"
    assert len(plan["itinerary"]) == 1
    _ok("plan_formatter from pipeline")


def test_tpc_agent_run_with_real_query() -> None:
    """TPCAgent.run 接口测试（pipeline 未就绪时应返回空 plan，不崩溃）。"""
    sample = ROOT / "data" / "training data" / "20250324234255286741.json"
    if not sample.exists():
        print("  [SKIP] 无 training data")
        return

    with open(sample, encoding="utf-8") as f:
        query = json.load(f)

    agent = TPCAgent(log_dir=str(ROOT / "data" / "outputs" / "cache" / "test"))
    succ, plan = agent.run(query, prob_idx=query["uid"], oralce_translation=False)

    assert "people_number" in plan
    assert "start_city" in plan
    assert "target_city" in plan
    assert "itinerary" in plan
    assert "elapsed_time(sec)" in plan
    # pipeline 未实现时 succ=False 但结构正确
    _ok(f"TPCAgent.run -> succ={succ}, itinerary_len={len(plan['itinerary'])}")


def test_run_single_official_query() -> None:
    """runner 层单条执行测试。"""
    query = {
        "uid": "demo",
        "nature_language": "test",
        "people_number": 1,
        "start_city": "上海",
        "target_city": "北京",
        "days": 2,
    }
    succ, plan = run_single_official_query(query, prob_idx="demo", oracle_translation=False)
    assert isinstance(plan, dict)
    assert plan["start_city"] == "上海"
    _ok(f"run_single_official_query -> succ={succ}")


def main() -> None:
    print("=" * 50)
    print("adapter 层测试")
    print("=" * 50)
    test_query_adapter_strips_oracle()
    test_plan_formatter_empty()
    test_plan_formatter_from_pipeline()
    test_run_single_official_query()
    test_tpc_agent_run_with_real_query()
    print("=" * 50)
    print("全部 adapter 测试通过")
    print("=" * 50)


if __name__ == "__main__":
    main()
