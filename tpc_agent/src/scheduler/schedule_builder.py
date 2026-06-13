"""时间表生成（activity 时间已在 planner 中生成）。"""

from src.data_layer.schema import Plan
from src.scheduler.time_window_checker import apply_time_window_check


def build_schedule(plan: Plan) -> Plan:
    """确认各 activity 时间有效并记录问题。"""
    return apply_time_window_check(plan)
