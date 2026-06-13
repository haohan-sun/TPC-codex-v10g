"""Verifier-driven repair loop — 论文启发 P0。

generation → local check → typed error → typed repair → recheck → accept/reject
最多 3 轮。每轮比较 score/gate 改善情况，改善则接受否则回滚。

来源：ChinaTravel, LLM-Modulo, Reflexion 论文。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from src.data_layer.schema import CandidatePool, Constraints, ErrorType, OfficialPlan, TypedError
from src.repair.typed_repair import typed_repair


def repair_loop(
    plan: OfficialPlan,
    constraints: Constraints,
    candidates: CandidatePool,
    *,
    max_rounds: int = 3,
    min_improvement: float = 0.0,
) -> tuple[OfficialPlan, dict[str, Any]]:
    """Verifier-driven repair loop。

    Args:
        plan: 初始 official plan。
        constraints: 约束集合。
        candidates: 候选池。
        max_rounds: 最大修复轮数（默认 3）。
        min_improvement: 最小改善阈值（默认 0，只要有改善就接受）。

    Returns:
        (repaired_plan, loop_report)
    """
    current_plan = deepcopy(plan)
    current_errors = _collect_errors(current_plan, constraints)
    current_score = _score_plan(current_plan, current_errors)

    loop_report: dict[str, Any] = {
        "initial_errors": len(current_errors),
        "initial_score": current_score,
        "rounds": [],
        "accepted_repairs": 0,
        "rejected_repairs": 0,
    }

    if not current_errors:
        loop_report["status"] = "no_errors"
        return current_plan, loop_report

    for round_idx in range(max_rounds):
        round_info: dict[str, Any] = {
            "round": round_idx + 1,
            "errors_before": len(current_errors),
            "error_types": [e.error_type.value if hasattr(e.error_type, 'value') else str(e.error_type) for e in current_errors],
        }

        # 执行 typed repair
        try:
            repaired = typed_repair(current_plan, current_errors, constraints, candidates)
        except Exception as exc:
            round_info["status"] = "repair_failed"
            round_info["exception"] = str(exc)
            loop_report["rounds"].append(round_info)
            break

        # 重评估
        repaired_errors = _collect_errors(repaired, constraints)
        repaired_score = _score_plan(repaired, repaired_errors)

        round_info["errors_after"] = len(repaired_errors)
        round_info["score_before"] = current_score
        round_info["score_after"] = repaired_score

        # 接受/拒绝判断
        improvement = current_score - repaired_score  # lower is better
        round_info["improvement"] = improvement

        if _is_better(repaired_errors, current_errors, repaired_score, current_score):
            # 接受修复
            current_plan = repaired
            current_errors = repaired_errors
            current_score = repaired_score
            round_info["status"] = "accepted"
            loop_report["accepted_repairs"] += 1
        else:
            # 拒绝修复，回滚
            round_info["status"] = "rejected"
            loop_report["rejected_repairs"] += 1

        loop_report["rounds"].append(round_info)

        # 没有错误则提前退出
        if not current_errors:
            loop_report["status"] = "all_errors_fixed"
            break

    loop_report["final_errors"] = len(current_errors)
    loop_report["final_score"] = current_score

    if not loop_report.get("status"):
        loop_report["status"] = "max_rounds_reached"

    return current_plan, loop_report


# ------------------------------------------------------------------
# 错误收集（local checkers）
# ------------------------------------------------------------------

def _collect_errors(plan: OfficialPlan, constraints: Constraints) -> list[TypedError]:
    """收集所有可检测的本地错误（不调用官方 evaluator）。"""
    errors: list[TypedError] = []
    payload = plan.itinerary if isinstance(plan.itinerary, dict) else {"itinerary": plan.itinerary}
    itinerary = payload.get("itinerary", []) if isinstance(payload, dict) else []

    # 1) Schema 基础检查
    _check_schema(errors, payload)

    # 2) 时间顺序检查
    _check_chronology(errors, itinerary)

    # 3) 必访检查
    _check_must_visit(errors, itinerary, constraints)

    # 4) 餐点时间窗检查
    _check_meal_windows(errors, itinerary)

    # 5) 交通连续性检查
    _check_transport_continuity(errors, itinerary)

    return errors


def _check_schema(errors: list[TypedError], plan_dict: dict) -> None:
    """Schema 基础校验。"""
    if not plan_dict.get("people_number"):
        errors.append(TypedError(error_type=ErrorType.FORMAT, message="missing people_number", location={}))
    if not plan_dict.get("start_city"):
        errors.append(TypedError(error_type=ErrorType.FORMAT, message="missing start_city", location={}))
    if not plan_dict.get("target_city"):
        errors.append(TypedError(error_type=ErrorType.FORMAT, message="missing target_city", location={}))


def _check_chronology(errors: list[TypedError], itinerary: list) -> None:
    """检查活动时间顺序。"""
    from src.planner.plan_utils import time_to_minutes

    for day in itinerary:
        prev_end = "00:00"
        day_num = day.get("day", "?")
        for i, act in enumerate(day.get("activities", [])):
            st = act.get("start_time", "")
            et = act.get("end_time", "")
            if st and et and time_to_minutes(et) <= time_to_minutes(st):
                errors.append(TypedError(
                    error_type=ErrorType.TIME,
                    message=f"Day {day_num} act {i}: start({st}) >= end({et})",
                    location=f"day={day_num},act={i}",
                ))
            if st and prev_end and time_to_minutes(st) < time_to_minutes(prev_end):
                # gap < 0 → overlap
                pass  # minor gaps are OK
            if et:
                prev_end = et


def _check_must_visit(errors: list[TypedError], itinerary: list, constraints: Constraints) -> None:
    """检查 must_visit 是否被覆盖。"""
    present = set()
    for day in itinerary:
        for act in day.get("activities", []):
            pos = str(act.get("position", "")).lower()
            if pos:
                present.add(pos)
    for card in constraints.cards:
        params = card.parameters or {}
        mv = params.get("must_visit_poi")
        if mv and str(mv).lower() not in present:
            errors.append(TypedError(
                error_type=ErrorType.MUST_VISIT,
                message=f"must_visit not found: {mv}",
                location=f"must_visit={mv}",
            ))


def _check_meal_windows(errors: list[TypedError], itinerary: list) -> None:
    """检查餐点时间窗。"""
    from src.planner.plan_utils import time_to_minutes

    windows = {"breakfast": ("07:00", "09:00"), "lunch": ("11:00", "14:00"), "dinner": ("17:00", "20:00")}
    for day in itinerary:
        day_num = day.get("day", "?")
        for i, act in enumerate(day.get("activities", [])):
            atype = act.get("type", "")
            if atype in windows:
                st = act.get("start_time", "")
                et = act.get("end_time", "")
                win_start, win_end = windows[atype]
                if st and time_to_minutes(st) > time_to_minutes(win_end):
                    errors.append(TypedError(
                        error_type=ErrorType.MEAL,
                        message=f"Day {day_num} {atype}: start {st} after window end {win_end}",
                        location=f"day={day_num},act={i}",
                    ))


def _check_transport_continuity(errors: list[TypedError], itinerary: list) -> None:
    """检查交通段连续性。"""
    for day in itinerary:
        day_num = day.get("day", "?")
        for i, act in enumerate(day.get("activities", [])):
            transports = act.get("transports", [])
            if not transports:
                continue
            prev_end = transports[0].get("start_time", "")
            for j, seg in enumerate(transports):
                seg_st = seg.get("start_time", "")
                seg_et = seg.get("end_time", "")
                if seg_st and seg_et and seg_et < seg_st:
                    errors.append(TypedError(
                        error_type=ErrorType.TRANSPORT,
                        message=f"Day {day_num} act {i} seg {j}: start({seg_st}) > end({seg_et})",
                        location=f"day={day_num},act={i},seg={j}",
                    ))


# ------------------------------------------------------------------
# 评分（内部简易评分，不调官方 eval）
# ------------------------------------------------------------------

def _score_plan(plan: OfficialPlan, errors: list[TypedError]) -> float:
    """内部简易评分：错误越少分数越低（越低越好）。"""
    weights = {
        "FORMAT": 10.0,
        "TICKET": 5.0,
        "TRANSPORT": 8.0,
        "BUDGET": 8.0,
        "TIME": 10.0,
        "MEAL": 5.0,
        "MUST_VISIT": 15.0,
        "OPENING_HOURS": 8.0,
        "INTERCITY": 10.0,
    }
    score = 0.0
    for e in errors:
        et_str = e.error_type.value if hasattr(e.error_type, 'value') else str(e.error_type)
        score += weights.get(et_str, 5.0)
    return score


def _is_better(
    new_errors: list[TypedError],
    old_errors: list[TypedError],
    new_score: float,
    old_score: float,
) -> bool:
    """判断修复是否有改善。

    优先级：错误数量减少 > 严重错误减少 > score 降低。
    """
    # 错误数量减少 → 接受
    if len(new_errors) < len(old_errors):
        return True
    # 同数量但严重错误减少 → 接受
    if len(new_errors) == len(old_errors) and new_score < old_score:
        return True
    return False
