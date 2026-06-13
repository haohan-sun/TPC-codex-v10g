"""全流程共享数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


@dataclass
class Query:
    """原始用户查询。"""

    query_id: str
    raw_text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConstraintCard:
    """单条约束卡片。"""

    card_id: str
    category: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    priority: int = 1
    is_hard: bool = True
    source: str = "user"


@dataclass
class Constraints:
    """约束集合。"""

    query_id: str
    cards: list[ConstraintCard] = field(default_factory=list)
    global_params: dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskProfile:
    """约束风险画像。"""

    query_id: str
    risk_scores: dict[str, float] = field(default_factory=dict)
    high_risk_categories: list[str] = field(default_factory=list)


@dataclass
class ActiveInfo:
    """主动查询补全信息。"""

    query_id: str
    priority_queries: list[str] = field(default_factory=list)
    fetched_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class GroundedPreferences:
    """语义落地后的偏好权重。"""

    query_id: str
    poi_weights: dict[str, float] = field(default_factory=dict)
    cuisine_weights: dict[str, float] = field(default_factory=dict)
    pace_weight: float = 0.5
    transport_weight: float = 0.5
    budget_weight: float = 0.5
    tags: dict[str, Any] = field(default_factory=dict)


@dataclass
class POICandidate:
    """POI 候选。"""

    poi_id: str
    name: str
    score: float = 0.0
    region: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CandidatePool:
    """候选池。"""

    query_id: str
    pois: list[POICandidate] = field(default_factory=list)
    hotels: list[POICandidate] = field(default_factory=list)
    restaurants: list[POICandidate] = field(default_factory=list)
    transports: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DayAssignment:
    """单日 POI 分配。"""

    day_index: int
    date: str
    poi_ids: list[str] = field(default_factory=list)


@dataclass
class PlanState:
    """滚动规划状态。"""

    current_day: int = 0
    remaining_budget: float = 0.0
    current_location: dict[str, Any] = field(default_factory=dict)
    remaining_must_visit: list[str] = field(default_factory=list)
    visited_poi_ids: list[str] = field(default_factory=list)


@dataclass
class Activity:
    """日内活动节点。"""

    activity_id: str
    poi_id: str
    name: str
    activity_type: str
    start_time: str = ""
    end_time: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DayPlan:
    """单日计划。"""

    day_index: int
    date: str
    activities: list[Activity] = field(default_factory=list)
    route_order: list[str] = field(default_factory=list)


@dataclass
class Plan:
    """内部行程计划（多日表示）。"""

    query_id: str
    policy: str = "safe"
    day_assignments: list[DayAssignment] = field(default_factory=list)
    day_plans: list[DayPlan] = field(default_factory=list)
    total_cost: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OfficialPlan:
    """官方提交格式行程。"""

    query_id: str
    itinerary: dict[str, Any] = field(default_factory=dict)
    version: str = "1.0"


class ErrorType(str, Enum):
    """错误类型枚举。"""

    BUDGET = "budget"
    TIME = "time"
    TRANSPORT = "transport"
    TICKET = "ticket"
    MEAL = "meal"
    MUST_VISIT = "must_visit"
    FORMAT = "format"
    OPENING_HOURS = "opening_hours"
    MISSING_BREAKFAST = "missing_breakfast"
    TRANSPORT_CONTINUITY = "transport_continuity"
    TRANSPORT_INFO = "transport_info"
    HARD_LOGIC_MISSING_ATTRACTION = "hard_logic_missing_attraction"
    HARD_LOGIC_ATTRACTION_TYPE = "hard_logic_attraction_type"
    HARD_LOGIC_BUDGET = "hard_logic_budget"
    UNKNOWN = "unknown"


@dataclass
class VerifierError:
    """Verifier 单条错误。"""

    error_code: str
    message: str
    error_type: ErrorType = ErrorType.UNKNOWN
    location: dict[str, Any] = field(default_factory=dict)


@dataclass
class TypedError:
    """类型化错误（供修复使用）。"""

    error_type: ErrorType
    message: str
    location: dict[str, Any] = field(default_factory=dict)
    repair_hint: str = ""


@dataclass
class VerifierOutput:
    """Verifier 返回。"""

    score: float
    errors: list[VerifierError] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    """多候选搜索结果。"""

    query_id: str
    best_plan: OfficialPlan
    best_score: float
    all_candidates: list[tuple[OfficialPlan, float, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Active Constraint Mapping (Active SLAM upgrade)
# ---------------------------------------------------------------------------

@dataclass
class ConstraintBelief:
    """单个约束维度的 belief state。"""

    category: str
    resolved: bool = False             # 是否已完全澄清
    confidence: float = 0.0            # 当前置信度 0-1
    missing_data: list[str] = field(default_factory=list)  # 缺失的数据类型
    risk_level: float = 0.0            # 该维度错误风险
    last_query_result: dict[str, Any] = field(default_factory=dict)  # 最近一次查询结果摘要


@dataclass
class ActiveAction:
    """主动查询动作 — 对应一条 agent_env structured tool call。"""

    action_id: str
    tool_name: str                     # agent_env tool name (goto, attractions_nearby, ...)
    params: dict[str, Any] = field(default_factory=dict)
    target_category: str = ""          # 目标约束维度
    risk_reason: str = ""              # 为什么需要查这个
    expected_info_gain: float = 0.0
    query_cost: float = 0.0
    priority_score: float = 0.0        # info_gain / (cost + epsilon)
    selected: bool = False             # 是否被选中执行
    selection_reason: str = ""         # 选中/未选中原因
    expected_output_keys: list[str] = field(default_factory=list)


@dataclass
class ActionSelectionResult:
    """一次 active constraint mapping 的完整结果。"""

    query_id: str
    beliefs: dict[str, ConstraintBelief] = field(default_factory=dict)   # category → belief
    all_actions: list[ActiveAction] = field(default_factory=list)         # 所有候选动作
    selected_actions: list[ActiveAction] = field(default_factory=list)    # 被选中的动作
    rejected_actions: list[ActiveAction] = field(default_factory=list)    # 被拒绝的动作
    total_expected_gain: float = 0.0
    total_query_cost: float = 0.0
    explanation_summary: list[str] = field(default_factory=list)
