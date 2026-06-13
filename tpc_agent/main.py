"""TPC 旅游行程规划 Agent — 可执行总流程入口。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Union

from src.data_layer.paths import load_project_config

from src.active.active_query_selector import active_query_selector
from src.active.constraint_risk_estimator import estimate_constraint_risk
from src.candidates.candidate_generator import build_candidates
from src.constraints.constraint_parser import parse_constraints
from src.data_layer.loaders import load_query, query_from_dict
from src.data_layer.schema import OfficialPlan, Plan, Query
from src.experiments.experiment_logger import save_logs
from src.optimizer.day_route_optimizer import optimize_daily_routes
from src.planner.poi_task_assignment import allocate_pois_to_days
from src.planner.rolling_day_planner import rolling_horizon_plan
from src.repair.typed_repair import typed_repair
from src.scheduler.budget_controller import control_budget
from src.scheduler.schedule_builder import build_schedule
from src.semantic.semantic_grounder import semantic_grounding
from src.submission.submission_writer import render_to_official_format
from src.verifier.error_parser import parse_errors
from src.verifier.local_checker import run_local_checker
from src.verifier.official_verifier_runner import run_official_verifier

# 多策略候选搜索策略列表
POLICIES = ["safe", "budget", "preference", "low_transport", "must_visit_first"]


def _load_config() -> dict[str, Any]:
    """加载 config.yaml（无 PyYAML 时使用 paths 模块 fallback）。"""
    return load_project_config()


def _normalize_query(query: Union[Query, dict[str, Any], str, Path]) -> Query:
    """统一 query 输入格式。"""
    if isinstance(query, Query):
        return query
    if isinstance(query, (str, Path)):
        return load_query(query)
    return query_from_dict(query)


def _repair_loop(
    plan: OfficialPlan,
    constraints,
    candidates,
    max_rounds: int,
) -> tuple[OfficialPlan, float, list]:
    """verifier 检查 → 错误分类 → 类型化修复 循环。"""
    score, errors = run_official_verifier(plan)

    for _ in range(max_rounds):
        if not errors:
            break
        typed_errors = parse_errors(errors)
        plan = typed_repair(
            plan=plan,
            errors=typed_errors,
            constraints=constraints,
            candidates=candidates,
        )
        score, errors = run_official_verifier(plan)

    return plan, score, errors


def solve_one_query(query: Union[Query, dict[str, Any], str, Path]) -> dict[str, Any]:
    """可执行总流程：普遍骨架 + 模块化优化点。

    用户自然语言需求
    → 约束卡片抽取
    → 主动约束获取（风险驱动）
    → 语义落地与偏好权重
    → 候选池构建
    → [多策略] 多日任务分配 → 滚动逐日规划 → 日内路线优化
    → 时间表生成 → 预算控制 → 本地检查
    → 官方格式 → 官方 verifier → 类型化修复
    → 多候选择优 → 最终输出
    """
    config = _load_config()
    planning = config.get("planning") or {}
    max_repair_rounds = planning.get("max_repair_rounds", 3)
    policies = planning.get("policies", POLICIES)

    # 1. 读取用户需求
    user_query = _normalize_query(query)

    # 2. 约束卡片抽取
    constraints = parse_constraints(user_query)

    # 3. 主动约束获取：先判风险，再查关键数据
    risk_profile = estimate_constraint_risk(user_query, constraints)
    active_info = active_query_selector(
        constraints=constraints,
        risk_profile=risk_profile,
    )

    # 4. 语义落地与偏好权重
    grounded_preferences = semantic_grounding(
        constraints=constraints,
        active_info=active_info,
    )

    # 5. 候选池构建（压缩搜索空间）
    candidates = build_candidates(
        constraints=constraints,
        preferences=grounded_preferences,
    )

    # 6-15. 多策略候选搜索 + verifier 择优
    best_plan: OfficialPlan | None = None
    best_score: float = -1.0
    all_results: list[tuple[OfficialPlan, float, str]] = []

    for policy in policies:
        # 6. 多日任务分配
        plan: Plan = allocate_pois_to_days(
            constraints=constraints,
            candidates=candidates,
            policy=policy,
        )

        # 7. 滚动时域逐日规划
        plan = rolling_horizon_plan(
            constraints=constraints,
            candidates=candidates,
            initial_plan=plan,
            preferences=grounded_preferences,
        )

        # 8. 日内路线优化
        plan = optimize_daily_routes(plan)

        # 9. 时间表生成
        plan = build_schedule(plan)

        # 10. 预算控制
        plan = control_budget(plan, constraints)

        # 11. 本地轻量检查
        plan = run_local_checker(plan, constraints)

        # 12. 生成官方格式
        official_plan = render_to_official_format(plan)

        # 13-14. 官方 verifier + 类型化修复
        official_plan, score, errors = _repair_loop(
            plan=official_plan,
            constraints=constraints,
            candidates=candidates,
            max_rounds=max_repair_rounds,
        )

        all_results.append((official_plan, score, policy))
        if score > best_score:
            best_plan = official_plan
            best_score = score

    if best_plan is None:
        raise RuntimeError(f"[{user_query.query_id}] 未生成任何候选行程")

    # 15. 实验记录
    save_logs(
        query=user_query,
        constraints=constraints,
        best_plan=best_plan,
        best_score=best_score,
        all_results=all_results,
    )

    # 16. 最终输出
    return {
        "query_id": user_query.query_id,
        "score": best_score,
        "itinerary": best_plan.itinerary,
        "policy_count": len(policies),
        "candidates_tried": [p for _, _, p in all_results],
    }


def main() -> None:
    """CLI 入口。"""
    if len(sys.argv) > 1:
        result = solve_one_query(sys.argv[1])
    else:
        query_data = json.load(sys.stdin)
        result = solve_one_query(query_data)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
