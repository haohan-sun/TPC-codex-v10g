"""修复：格式错误。"""

from src.data_layer.schema import OfficialPlan


def repair_format(plan: OfficialPlan, error_detail: str) -> OfficialPlan:
    """修正 JSON 格式字段。

    Args:
        plan: 当前行程。
        error_detail: 格式错误描述。

    Returns:
        OfficialPlan: 修复后行程。
    """
    raise NotImplementedError
