"""TPC 旅游行程规划 Agent — 可执行总流程入口。"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Union

from src.data_layer.paths import load_project_config
from src.data_layer.world_env_client import get_sandbox

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
from src.search.policy_generator import generate_policies
from src.search.plan_selector import select_best_plan
from src.verifier.error_parser import parse_errors
from src.verifier.local_checker import run_local_checker
from src.verifier.official_verifier_runner import run_official_verifier

# 多策略候选搜索策略列表
POLICIES = ["safe", "budget", "preference", "low_transport", "must_visit_first"]
# P0 fast fallback: 只用最快两个 policy，避免 timeout
FAST_POLICIES = ["safe", "must_visit_first"]
# SEV0 降级：极度压力下只用 safe，禁用 GA-TSP extras
SEV0_POLICIES = ["safe"]


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


def _convert_local_issues_to_errors(issues: list[str]) -> list:
    """Convert local_check_issues strings into TypedError-like objects."""
    from src.data_layer.schema import ErrorType
    type_map = {
        "MISSING_BREAKFAST": ErrorType.MISSING_BREAKFAST,
        "TRANSPORT_CONTINUITY": ErrorType.TRANSPORT_CONTINUITY,
        "TRANSPORT_INFO": ErrorType.TRANSPORT_INFO,
        "HARD_LOGIC_MISSING_ATTRACTION": ErrorType.HARD_LOGIC_MISSING_ATTRACTION,
        "HARD_LOGIC_ATTRACTION_TYPE": ErrorType.HARD_LOGIC_ATTRACTION_TYPE,
        "HARD_LOGIC_BUDGET": ErrorType.HARD_LOGIC_BUDGET,
        "TIME_ORDER": ErrorType.TIME,
        "TICKET": ErrorType.TICKET,
        "SCHEMA": ErrorType.FORMAT,
    }
    result = []
    for issue in issues:
        code = issue.split(" ")[0] if " " in issue else issue
        et = type_map.get(code, ErrorType.FORMAT)
        result.append(type("TypedError", (), {
            "error_code": code, "message": issue, "error_type": et,
        }))
    return result


def _repair_loop(
    plan: OfficialPlan,
    constraints,
    candidates,
    max_rounds: int,
    local_issues: list[str] | None = None,
) -> tuple[OfficialPlan, float, list]:
    """verifier 检查 → 错误分类 → 类型化修复 循环。"""
    # First pass: fix local issues before official verifier
    if local_issues:
        local_errors = _convert_local_issues_to_errors(local_issues)
        plan = typed_repair(
            plan=plan, errors=local_errors,
            constraints=constraints, candidates=candidates,
        )

    score, errors = run_official_verifier(plan)

    for _ in range(max_rounds):
        if not errors:
            break
        typed_errors = parse_errors(errors)
        if not typed_errors:
            break
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
    t_start = time.monotonic()
    config = _load_config()
    planning = config.get("planning") or {}
    max_repair_rounds = planning.get("max_repair_rounds", 3)

    # 全局 deadline 熔断：默认 120s 硬 deadline，可通过 config 调整
    deadline_sec = planning.get("deadline_sec", 120)
    deadline_end = t_start + deadline_sec

    def _deadline_exceeded() -> bool:
        return time.monotonic() > deadline_end

    # 清空沙盒缓存，确保每次 query 独立
    try:
        sandbox = get_sandbox()
        sandbox.clear_caches()
    except Exception:
        pass

    # 1. 读取用户需求
    user_query = _normalize_query(query)

    # 2. 约束卡片抽取
    constraints = parse_constraints(user_query)

    # 根据约束特征动态生成策略优先级
    policies = generate_policies(constraints, planning.get("policies", POLICIES))

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
    # fast_mode: 只用 2 个 policy, 1 轮 repair
    fast_mode = planning.get("fast_mode", True)
    effective_policies = FAST_POLICIES if fast_mode else policies

    # 根据 deadline 动态调整：时间紧时降级到单 policy
    if _deadline_exceeded():
        effective_policies = SEV0_POLICIES
    effective_repair = 1 if fast_mode else max_repair_rounds

    # 将 deadline 信息注入 metadata，供下游模块自适应
    plan_meta_deadline = {"deadline_end": deadline_end}

    best_plan: OfficialPlan | None = None
    best_score: float = -1.0
    all_results: list[tuple[OfficialPlan, float, str]] = []

    for policy in effective_policies:
        # deadline 熔断：不再启动新 policy
        if _deadline_exceeded():
            break

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

        # 8. 日内路线优化（根据 deadline 自适应 GA-TSP 参数）
        plan.metadata["deadline"] = plan_meta_deadline
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
            max_rounds=effective_repair,
        )

        all_results.append((official_plan, score, policy))

    if not all_results:
        # deadline 熔断时所有 policy 都没完成 — 快速构建保守 plan
        if _deadline_exceeded():
            plan_fast: Plan = allocate_pois_to_days(
                constraints=constraints, candidates=candidates, policy="safe",
            )
            plan_fast = rolling_horizon_plan(
                constraints=constraints, candidates=candidates,
                initial_plan=plan_fast, preferences=grounded_preferences,
            )
            plan_fast = optimize_daily_routes(plan_fast)
            plan_fast = build_schedule(plan_fast)
            plan_fast = control_budget(plan_fast, constraints)
            plan_fast = run_local_checker(plan_fast, constraints)
            official_fast = render_to_official_format(plan_fast)
            result = {
                "query_id": user_query.query_id,
                "score": 0.0,
                "itinerary": official_fast.itinerary,
                "policy_count": 1,
                "candidates_tried": ["safe"],
                "deadline_fallback": True,
            }
            save_logs(query=user_query, constraints=constraints,
                      best_plan=official_fast, best_score=0.0,
                      all_results=[(official_fast, 0.0, "safe")])
            return result
        raise RuntimeError(f"[{user_query.query_id}] 未生成任何候选行程")

    # best-of-N 择优：使用 search 模块的选择逻辑
    scored_candidates = [(p.itinerary, s, pol) for p, s, pol in all_results]
    best_plan_dict, best_score, best_policy = select_best_plan(scored_candidates)
    # 找到最高分的 OfficialPlan
    for official_plan, score, policy in all_results:
        if score == max(s for _, s, _ in all_results):
            best_plan = official_plan
            break

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
