"""修复：预算超限。"""

from src.data_layer.schema import CandidatePool, OfficialPlan


def repair_budget(plan: OfficialPlan, candidates: CandidatePool) -> OfficialPlan:
    """只替换酒店和交通等高成本项。

    Args:
        plan: 当前行程。
        candidates: 候选池。

    Returns:
        OfficialPlan: 修复后行程。
    """
    raise NotImplementedError
