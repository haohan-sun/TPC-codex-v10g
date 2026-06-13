"""修复：餐饮缺失。"""

from src.data_layer.schema import CandidatePool, OfficialPlan


def repair_meal(
    plan: OfficialPlan,
    candidates: CandidatePool,
    location: dict,
) -> OfficialPlan:
    """只在饭点附近插入餐厅。

    Args:
        plan: 当前行程。
        candidates: 候选池。
        location: 错误定位。

    Returns:
        OfficialPlan: 修复后行程。
    """
    raise NotImplementedError
