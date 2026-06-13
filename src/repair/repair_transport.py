"""修复：交通问题。"""

from src.data_layer.schema import OfficialPlan


def repair_transport(plan: OfficialPlan, location: dict) -> OfficialPlan:
    """只调整交通方式或路线顺序。

    Args:
        plan: 当前行程。
        location: 错误定位。

    Returns:
        OfficialPlan: 修复后行程。
    """
    raise NotImplementedError
