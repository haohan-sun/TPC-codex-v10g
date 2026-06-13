"""semantic + planner + submission + eval 集成测试。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.active.active_query_selector import active_query_selector
from src.active.constraint_risk_estimator import estimate_constraint_risk
from src.candidates.candidate_generator import build_candidates
from src.constraints.constraint_parser import parse_constraints
from src.data_layer.loaders import load_query
from src.planner.poi_task_assignment import allocate_pois_to_days
from src.planner.rolling_day_planner import rolling_horizon_plan
from src.semantic.semantic_grounder import semantic_grounding
from src.submission.submission_writer import render_to_official_format
from src.verifier.eval_bridge import evaluate_plan_local
from src.planner.constraint_profile import extract_planning_constraints
from src.data_layer.world_env_client import get_chinatravel_status


def _ok(name: str) -> None:
    print(f"  [PASS] {name}")


def test_pipeline_non_empty_itinerary() -> None:
    sample = ROOT / "data" / "training data" / "20250324234255286741.json"
    if not sample.exists():
        print("  [SKIP] 无 training data")
        return

    query = load_query(sample)
    constraints = parse_constraints(query)
    risk = estimate_constraint_risk(query, constraints)
    active_info = active_query_selector(constraints, risk)
    prefs = semantic_grounding(constraints, active_info)
    candidates = build_candidates(constraints, prefs)

    plan = allocate_pois_to_days(constraints, candidates, policy="safe")
    plan = rolling_horizon_plan(constraints, candidates, plan, preferences=prefs)

    official = render_to_official_format(plan)
    payload = official.itinerary

    assert payload.get("people_number") == 5
    assert payload.get("target_city") == "Chengdu"
    assert len(payload.get("itinerary", [])) == 3, "应有 3 天行程"

    total_acts = sum(len(d.get("activities", [])) for d in payload["itinerary"])
    assert total_acts > 0, "activities 不应为空"

    # 检查 activity 结构
    act = payload["itinerary"][0]["activities"][0]
    for field in ("type", "start_time", "end_time", "cost", "price", "transports"):
        assert field in act, f"缺少 {field}"

    eval_result = evaluate_plan_local(payload, query_id=query.query_id)
    pc = extract_planning_constraints(constraints)
    ct_status = get_chinatravel_status()

    # 票务约束
    for day in payload["itinerary"]:
        for act in day.get("activities", []):
            if act.get("type") in ("attraction", "airplane", "train"):
                assert act.get("tickets") == pc.people, f"tickets 应为 {pc.people}"

    assert eval_result["score"] >= 0
    _ok(
        f"itinerary: {len(payload['itinerary'])} 天, {total_acts} activity, "
        f"score={eval_result['score']}, CT={ct_status['database_ready']}"
    )


def test_tpc_agent_run() -> None:
    from tpc_agent import TPCAgent

    sample = ROOT / "data" / "training data" / "20250322220423800679.json"
    if not sample.exists():
        print("  [SKIP]")
        return
    with open(sample, encoding="utf-8") as f:
        q = json.load(f)
    agent = TPCAgent(log_dir=str(ROOT / "data" / "outputs" / "cache" / "test_pipeline"))
    succ, plan = agent.run(q, prob_idx=q["uid"], oralce_translation=False)
    assert len(plan.get("itinerary", [])) > 0
    _ok(f"TPCAgent.run succ={succ}, days={len(plan['itinerary'])}")


def main() -> None:
    print("=" * 50)
    print("pipeline 集成测试")
    print("=" * 50)
    test_pipeline_non_empty_itinerary()
    test_tpc_agent_run()
    print("=" * 50)
    print("全部通过")
    print("=" * 50)


if __name__ == "__main__":
    main()
