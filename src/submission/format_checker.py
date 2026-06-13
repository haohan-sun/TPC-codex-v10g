"""提交格式校验。"""

import re

from src.data_layer.schema import OfficialPlan

# 官方 output_schema.json: start_time / end_time 必须匹配 ^\d{2}:\d{2}$
_TIME_RE = re.compile(r"^\d{2}:\d{2}$")


def check_format(plan: OfficialPlan) -> list[str]:
    """校验 JSON 字段完整性与时间格式。

    Args:
        plan: 官方格式行程。

    Returns:
        list[str]: 格式问题列表。
    """
    payload = plan.itinerary or {}
    issues: list[str] = []

    for field in ("people_number", "start_city", "target_city", "itinerary"):
        if field not in payload:
            issues.append(f"missing top-level field: {field}")

    itinerary = payload.get("itinerary")
    if not isinstance(itinerary, list):
        issues.append("itinerary must be a list")
        return issues

    for day_idx, day in enumerate(itinerary, start=1):
        if not isinstance(day, dict):
            issues.append(f"day {day_idx} must be an object")
            continue
        if "day" not in day:
            issues.append(f"day {day_idx} missing field: day")
        activities = day.get("activities")
        if not isinstance(activities, list):
            issues.append(f"day {day_idx} activities must be a list")
            continue
        for act_idx, act in enumerate(activities, start=1):
            if not isinstance(act, dict):
                issues.append(f"day {day_idx} activity {act_idx} must be an object")
                continue
            for field in ("type", "start_time", "end_time", "cost"):
                if field not in act:
                    issues.append(f"day {day_idx} activity {act_idx} missing field: {field}")
            # 三位数时间检测（官方 schema: ^\d{2}:\d{2}$）
            for time_field in ("start_time", "end_time"):
                t = act.get(time_field, "")
                if t and not _TIME_RE.match(str(t)):
                    issues.append(
                        f"day {day_idx} activity {act_idx} {time_field}={t!r} "
                        f"不符合 HH:MM 格式（官方 schema 要求 ^\\d{{2}}:\\d{{2}}$）"
                    )
            if act.get("type") in {"airplane", "train"}:
                for field in ("start", "end"):
                    if field not in act:
                        issues.append(f"day {day_idx} activity {act_idx} missing field: {field}")
            elif "position" not in act:
                issues.append(f"day {day_idx} activity {act_idx} missing field: position")
            transports = act.get("transports", [])
            if transports is not None and not isinstance(transports, list):
                issues.append(f"day {day_idx} activity {act_idx} transports must be a list")
            else:
                for seg_idx, seg in enumerate(transports or []):
                    for time_field in ("start_time", "end_time"):
                        t = seg.get(time_field, "")
                        if t and not _TIME_RE.match(str(t)):
                            issues.append(
                                f"day {day_idx} activity {act_idx} transport[{seg_idx}] "
                                f"{time_field}={t!r} 不符合 HH:MM 格式"
                            )

    return issues
