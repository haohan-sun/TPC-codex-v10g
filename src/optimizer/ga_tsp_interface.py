"""GA-TSP 遗传算法路线优化 — 接口定义与说明。

== 目的 ==

为 ``day_route_optimizer.py`` 的未来 GA-TSP 替换定义清晰的输入/输出契约。
当前优化链路为 greedy nearest-neighbor + 2-opt local search；
GA-TSP 作为可选的增强优化器，应在保持相同接口的前提下提供更优的全局搜索能力。

== 当前数据流（day_route_optimizer.py）==

1. ``optimize_daily_routes(plan: Plan)`` 从 ``plan.metadata["official_plan"]["itinerary"]`` 获取每天的 activities。
2. 每天筛选 ``type == "attraction"`` 的活动作为可重排节点。
3. ``_start_anchor_for_day()`` 从第一个 attraction 之前的 activity 中获取起点位置。
4. ``_optimized_attraction_order()``:
   a. 构建距离矩阵（优先 WorldEnv.poi_distance → Haversine → 3km fallback）
   b. 从 anchor 出发做 greedy nearest-neighbor
   c. 用 2-opt 局部搜索改进
5. ``_retime_day()`` 按新顺序重新计算所有活动的 start_time/end_time。

== GA-TSP 需要的最小输入 ==

以下 7 类输入是从当前数据流中可以无损提取的：

1. **day_attractions** : ``list[DayAttraction]``
   每天需要排序的景点列表。每个景点含：
   - name (position 字段，用于 goto 查询)
   - opening_time / closing_time (如 "09:00" / "17:00")
   - duration_min (推荐游览分钟数)
   - must_visit (bool, 是否必去，必去项不能因时间不足而跳过)
   - price / tickets (用于成本计算)

2. **start_position** : ``str``
   当天的起点位置（通常是前一晚酒店 position，或城际交通到达站）。

3. **end_position** : ``str | None``
   当天终点位置（通常是当晚酒店 position）。如果为 None，
   说明当天是最后一天，不需要回到酒店。

4. **distance_matrix** : ``TransportMatrix``
   POI 间 pairwise 距离/时间/成本矩阵。当前由 ``_distance()`` 函数
   动态计算（lazy），对 GA-TSP 建议预计算为稠密矩阵以加速 fitness 评估。

5. **opening_hours_info** : ``dict[str, tuple[str, str]]``
   POI name → (opentime, endtime)，如 ``{"故宫": ("08:30", "17:00")}``。
   当前代码中景点开放时间从 ``poi_meta`` 的 metadata 中按需读取，
   GA-TSP 阶段应显式传入。

6. **transport_modes** : ``list[str]``
   可用交通方式列表，如 ``["metro", "taxi", "walk"]``。
   fitness 评估时应为每段选择最合适的 transport mode。

7. **must_visit_flags** : ``set[str]``
   必去景点名称集合。GA-TSP 的 fitness 函数应惩罚缺失必去项。

== GA-TSP 期望输出 ==

``GATSPResult``:
- **ordered_names**: ``list[str]`` — 优化后的景点访问顺序
- **transport_plan**: ``list[TransportSegment]`` — 每段交通的 mode/start_time/end_time/cost
- **total_cost**: ``float`` — 总成本（交通 + 门票）
- **total_time_min**: ``float`` — 交通总耗时（分钟）
- **feasible**: ``bool`` — 是否满足所有硬约束（开放时间/必去/时间窗口）
- **violations**: ``list[str]`` — 违反的约束描述
- **generations**: ``int`` — 实际运行代数
- **convergence_curve**: ``list[float]`` — 每代最优 fitness

== 插入点 ==

GA-TSP 应替换 ``day_route_optimizer.py`` 中的 ``_optimized_attraction_order()`` 函数。
当前调用链：

    optimize_daily_routes(plan)
      → 每天: _optimized_attraction_order(attraction_acts, city, sandbox, poi_meta, start_anchor)
                → _distance() 动态查询
                → greedy_from_anchor() → two_opt()

替换为：

    optimize_daily_routes(plan)          # 不变
      → 每天: _ga_tsp_order(             # 新增
            day_attractions=...,
            start_position=...,
            end_position=...,
            distance_matrix=...,
            opening_hours=...,
            transport_modes=...,
            must_visit=...,
            config=GATSPConfig(...),
        )

== 注意事项 ==

- 不要改动 optimize_daily_routes 的整体结构（保留 meal/hotel/intercity anchor）。
- 不要改动 Plan schema。
- GA-TSP 应和当前的 2-opt 共用相同的 ``_distance()`` 和 ``_retime_day()`` 函数。
- 如果 GA-TSP 在 < 10 秒内找不到可行解，应 fallback 到当前的 greedy + 2-opt。
- 首日的第一个 attraction 之前有城际交通到达站作为 anchor，GA-TSP 起点应为该到达站。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DayAttraction:
    """每天需要排序的单个景点。"""

    name: str                                    # POI position 名称
    opening_time: str = "09:00"                  # 开门时间 HH:MM
    closing_time: str = "17:00"                  # 关门时间 HH:MM
    duration_min: int = 90                       # 推荐游览分钟
    must_visit: bool = False                     # 是否必去
    price: float = 0.0                           # 单人票价
    tickets: int = 1                             # 票数
    metadata: dict[str, Any] = field(default_factory=dict)  # 原始数据


@dataclass
class TransportSegment:
    """单段交通。"""

    from_pos: str
    to_pos: str
    mode: str = "metro"                          # walk / metro / taxi
    start_time: str = ""
    end_time: str = ""
    cost: float = 0.0
    distance_km: float = 0.0
    duration_min: float = 0.0


@dataclass
class TransportMatrix:
    """POI 间 pairwise 交通矩阵。"""

    poi_names: list[str] = field(default_factory=list)
    distance_km: list[list[float]] = field(default_factory=list)   # [i][j]
    duration_min: list[list[float]] = field(default_factory=list)  # [i][j]
    cost: list[list[float]] = field(default_factory=list)          # [i][j]
    best_mode: list[list[str]] = field(default_factory=list)       # [i][j]

    def lookup(self, a: str, b: str) -> tuple[float, float, float, str]:
        """查询两点间距离/时间/成本/最佳模式。无数据时返回 fallback。"""
        try:
            i = self.poi_names.index(a)
            j = self.poi_names.index(b)
            return (
                self.distance_km[i][j] if i < len(self.distance_km) and j < len(self.distance_km[i]) else 3.0,
                self.duration_min[i][j] if i < len(self.duration_min) and j < len(self.duration_min[i]) else 15.0,
                self.cost[i][j] if i < len(self.cost) and j < len(self.cost[i]) else 5.0,
                self.best_mode[i][j] if i < len(self.best_mode) and j < len(self.best_mode[i]) else "metro",
            )
        except (ValueError, IndexError):
            return 3.0, 15.0, 5.0, "metro"


@dataclass
class GATSPConfig:
    """GA-TSP 超参数。"""

    population_size: int = 50
    generations: int = 200
    mutation_rate: float = 0.15
    crossover_rate: float = 0.80
    elite_count: int = 5
    tournament_size: int = 3
    max_stall_generations: int = 30            # 早停：连续 N 代无改进则终止
    timeout_sec: float = 10.0                   # 超时回退到 greedy + 2-opt
    transport_mode_penalty: dict[str, float] = field(default_factory=lambda: {
        "walk": 1.0,
        "metro": 0.8,
        "taxi": 1.5,                            # taxi 更贵但更快
    })
    opening_hours_penalty: float = 100.0         # 违反开放时间的惩罚权重
    must_visit_miss_penalty: float = 200.0       # 缺少必去景点的惩罚权重
    fatigue_penalty_per_poi: float = 0.05        # 每个额外景点的疲劳因子


@dataclass
class GATSPResult:
    """GA-TSP 优化结果。"""

    ordered_names: list[str] = field(default_factory=list)          # 优化后顺序
    transport_plan: list[TransportSegment] = field(default_factory=list)
    total_cost: float = 0.0
    total_time_min: float = 0.0
    feasible: bool = False
    violations: list[str] = field(default_factory=list)
    generations: int = 0
    convergence_curve: list[float] = field(default_factory=list)
    solver_used: str = "greedy_2opt"            # "ga_tsp" or "greedy_2opt" (fallback)


# ---------------------------------------------------------------------------
# 从当前数据结构提取 GA-TSP 输入的辅助函数（示意，不修改现有代码）
# ---------------------------------------------------------------------------

def extract_ga_tsp_inputs(
    attraction_acts: list[dict[str, Any]],
    start_anchor: str,
    end_anchor: str | None,
    poi_meta: dict[str, dict[str, Any]],
    must_visit_set: set[str],
) -> tuple[list[DayAttraction], str, str | None, set[str]]:
    """从当前的 day_route_optimizer 数据中提取 GA-TSP 输入。

    这是未来 ga_tsp 模块插入时的适配函数，当前仅供文档说明。

    Args:
        attraction_acts: 当前 day 的 attraction activity dict 列表。
        start_anchor: 起点 position（来自 _start_anchor_for_day）。
        end_anchor: 终点 position（来自 _overnight_position 或 None）。
        poi_meta: POI metadata 字典（来自 _poi_meta_by_name）。
        must_visit_set: 必去景点名称集合。

    Returns:
        (day_attractions, start_position, end_position, must_visit_flags)
    """
    day_attrs: list[DayAttraction] = []
    for act in attraction_acts:
        name = str(act.get("position", ""))
        if not name:
            continue
        meta = poi_meta.get(name, {})
        day_attrs.append(DayAttraction(
            name=name,
            opening_time=str(meta.get("opentime", "09:00")),
            closing_time=str(meta.get("endtime", "17:00")),
            duration_min=max(45, int(float(meta.get("recommendmintime", 1.5)) * 60)),
            must_visit=name in must_visit_set,
            price=float(meta.get("price", 0)),
            tickets=int(act.get("tickets", 1)),
            metadata=meta,
        ))
    return day_attrs, start_anchor, end_anchor, must_visit_set


def build_transport_matrix_spec(
    day_attrs: list[DayAttraction],
    sandbox,        # SandboxClient
    city: str,
) -> TransportMatrix:
    """预计算 TransportMatrix 的接口规格。

    当前 _distance() 函数用 lazy 查询，GA-TSP 应改用此预计算稠密矩阵。
    fitness 评估时不需重复查询 WorldEnv。

    注意：这是规格说明，不修改现有代码。
    """
    n = len(day_attrs)
    names = [a.name for a in day_attrs]
    dist = [[0.0] * n for _ in range(n)]
    dur = [[0.0] * n for _ in range(n)]
    cost = [[0.0] * n for _ in range(n)]
    mode = [["walk"] * n for _ in range(n)]

    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            # 复用当前 _distance() 逻辑
            try:
                d = sandbox.poi_distance(city, names[i], names[j], "09:00", "metro")
                if d is not None and d > 0:
                    dist[i][j] = d
                    dur[i][j] = d / 25.0 * 60.0  # 25km/h
                    cost[i][j] = 5.0              # metro base
                    mode[i][j] = "metro"
                else:
                    dist[i][j] = 3.0
                    dur[i][j] = 15.0
                    cost[i][j] = 5.0
                    mode[i][j] = "metro"
            except Exception:
                dist[i][j] = 3.0
                dur[i][j] = 15.0
                cost[i][j] = 5.0
                mode[i][j] = "metro"

    return TransportMatrix(
        poi_names=names,
        distance_km=dist,
        duration_min=dur,
        cost=cost,
        best_mode=mode,
    )
