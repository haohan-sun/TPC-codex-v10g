"""修复：时间冲突。"""

from src.data_layer.schema import OfficialPlan


def repair_time(plan: OfficialPlan, location: dict) -> OfficialPlan:
    """只调整顺序或换天，不改动无关活动。

    Args:
        plan: 当前行程。
        location: 错误定位。

    Returns:
        OfficialPlan: 修复后行程。
    """
    raise NotImplementedError
