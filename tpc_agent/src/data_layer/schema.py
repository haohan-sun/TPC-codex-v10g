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
    MEAL = "meal"
    MUST_VISIT = "must_visit"
    FORMAT = "format"
    OPENING_HOURS = "opening_hours"
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
