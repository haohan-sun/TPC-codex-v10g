"""修复：必去点遗漏。"""

from src.data_layer.schema import CandidatePool, OfficialPlan


def repair_must_visit(
    plan: OfficialPlan,
    candidates: CandidatePool,
    missing_poi_id: str,
) -> OfficialPlan:
    """强制插入必去 POI 并保护。

    Args:
        plan: 当前行程。
        candidates: 候选池。
        missing_poi_id: 遗漏的 POI ID。

    Returns:
        OfficialPlan: 修复后行程。
    """
    raise NotImplementedError
