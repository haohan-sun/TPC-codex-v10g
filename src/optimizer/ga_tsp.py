"""GA-TSP 遗传算法路线优化 — 完整实现。

基于 ``ga_tsp_interface.py`` 定义的契约，为 ``day_route_optimizer.py``
提供可替换 greedy + 2-opt 的 GA 全局搜索优化器。

编码: 排列编码 (permutation of attraction indices)
选择: 锦标赛选择 + 精英保留
交叉: OX (Order Crossover) — 保持相对顺序
变异: 逆转变异 + 交换变异
适应度: 多因素目标函数（距离/时间/成本/开放时间/必访优先级/疲劳）
"""

from __future__ import annotations

import random
import time
from typing import Any

from src.optimizer.ga_tsp_interface import (
    DayAttraction,
    GATSPConfig,
    GATSPResult,
    TransportMatrix,
)
from src.planner.plan_utils import time_to_minutes


class GATSPSolver:
    """GA-TSP 求解器。

    用法::

        solver = GATSPSolver(day_attrs, transport_matrix, config, start_pos, end_pos)
        result = solver.solve()
        if result.feasible:
            optimized_order = result.ordered_names
    """

    def __init__(
        self,
        day_attrs: list[DayAttraction],
        transport_matrix: TransportMatrix,
        config: GATSPConfig | None = None,
        start_position: str = "",
        end_position: str | None = None,
    ):
        self._attrs = day_attrs
        self._n = len(day_attrs)
        self._matrix = transport_matrix
        self._config = config or GATSPConfig()
        self._start_pos = start_position
        self._end_pos = end_position

        # 预计算适应度缓存
        self._fitness_cache: dict[tuple, float] = {}

        # 收敛曲线
        self._convergence: list[float] = []

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def solve(self) -> GATSPResult:
        """运行 GA-TSP 优化。

        如果景点数 <= 2 或超时，返回 fallback 结果。
        """
        if self._n <= 1:
            return GATSPResult(
                ordered_names=[a.name for a in self._attrs],
                feasible=True,
                solver_used="trivial",
            )
        if self._n == 2:
            return GATSPResult(
                ordered_names=[a.name for a in self._attrs],
                feasible=True,
                solver_used="trivial",
            )

        start_t = time.monotonic()

        try:
            result = self._run_ga(start_t)
        except Exception:
            result = GATSPResult(
                ordered_names=[a.name for a in self._attrs],
                feasible=False,
                solver_used="greedy_2opt",
                violations=["GA exception - fallback"],
            )

        elapsed = time.monotonic() - start_t
        if elapsed > self._config.timeout_sec:
            result.solver_used = "greedy_2opt"
            result.violations.append(f"timeout {elapsed:.1f}s")

        return result

    # ------------------------------------------------------------------
    # GA core
    # ------------------------------------------------------------------

    def _run_ga(self, start_t: float) -> GATSPResult:
        cfg = self._config
        pop = self._init_population()

        best_indices: list[int] = pop[0]
        best_fitness = self._fitness(best_indices)
        stall = 0

        for gen in range(cfg.generations):
            # 超时检查
            if time.monotonic() - start_t > cfg.timeout_sec:
                break

            # 精英保留
            pop.sort(key=self._fitness)
            new_pop = pop[: cfg.elite_count]

            # 生成下一代
            while len(new_pop) < cfg.population_size:
                # 选择
                p1 = self._tournament_select(pop)
                p2 = self._tournament_select(pop)

                # 交叉
                if random.random() < cfg.crossover_rate:
                    c1, c2 = self._ox_crossover(p1, p2)
                else:
                    c1, c2 = list(p1), list(p2)

                # 变异
                if random.random() < cfg.mutation_rate:
                    c1 = self._mutate(c1)
                if random.random() < cfg.mutation_rate:
                    c2 = self._mutate(c2)

                new_pop.append(c1)
                if len(new_pop) < cfg.population_size:
                    new_pop.append(c2)

            pop = new_pop

            # 评估
            current_best = min(pop, key=self._fitness)
            current_fitness = self._fitness(current_best)
            self._convergence.append(current_fitness)

            if current_fitness < best_fitness:
                best_indices = current_best
                best_fitness = current_fitness
                stall = 0
            else:
                stall += 1

            if stall >= cfg.max_stall_generations:
                break

        ordered_names = [self._attrs[i].name for i in best_indices]
        feasible = self._check_feasibility(best_indices)

        return GATSPResult(
            ordered_names=ordered_names,
            feasible=feasible,
            violations=[] if feasible else self._collect_violations(best_indices),
            generations=len(self._convergence),
            convergence_curve=self._convergence,
            solver_used="ga_tsp",
        )

    # ------------------------------------------------------------------
    # population init
    # ------------------------------------------------------------------

    def _init_population(self) -> list[list[int]]:
        """初始化种群：随机排列 + 贪心启发式。

        当 n! < population_size 时（少数景点），自动截断到可能排列数上限，
        避免死循环。
        """
        cfg = self._config
        pop: list[list[int]] = []

        # 贪心种子（最近邻 + 必访优先）
        greedy = self._greedy_seed()
        pop.append(greedy)

        # 必访优先种子
        must_first = self._must_visit_first_seed()
        if must_first != greedy:
            pop.append(must_first)

        # 开放时间优先种子（按开门时间排序）
        open_order = sorted(
            range(self._n),
            key=lambda i: time_to_minutes(self._attrs[i].opening_time),
        )
        if open_order not in pop:
            pop.append(open_order)

        # 计算最大可能排列数（n 小时自动截断 population_size）
        import math as _math
        max_perms = _math.factorial(self._n)
        target_size = min(cfg.population_size, max_perms)

        # 随机排列填充到 target_size
        base = list(range(self._n))
        max_attempts = target_size * 20  # 最多尝试次数
        attempts = 0
        while len(pop) < target_size and attempts < max_attempts:
            perm = base.copy()
            random.shuffle(perm)
            if perm not in pop:
                pop.append(perm)
            attempts += 1

        return pop

    def _greedy_seed(self) -> list[int]:
        """最近邻贪心构造（从起点开始）。"""
        unvisited = set(range(self._n))
        route: list[int] = []

        while unvisited:
            if not route:
                # 选离起点最近的
                best = min(unvisited, key=lambda i: self._dist_from_start(i))
            else:
                prev = route[-1]
                best = min(unvisited, key=lambda i: self._dist_between(prev, i))
            route.append(best)
            unvisited.discard(best)

        return route

    def _must_visit_first_seed(self) -> list[int]:
        """必访景点排前面，其余按最近邻。"""
        must = [i for i in range(self._n) if self._attrs[i].must_visit]
        others = [i for i in range(self._n) if not self._attrs[i].must_visit]

        # must 按开门时间排
        must.sort(key=lambda i: time_to_minutes(self._attrs[i].opening_time))
        # others 按最近邻排
        if must and others:
            current = must[-1]
            ordered_others: list[int] = []
            unvisited = set(others)
            while unvisited:
                nxt = min(unvisited, key=lambda i: self._dist_between(current, i))
                ordered_others.append(nxt)
                unvisited.discard(nxt)
                current = nxt
            return must + ordered_others

        return must + others

    # ------------------------------------------------------------------
    # fitness
    # ------------------------------------------------------------------

    def _fitness(self, indices: list[int]) -> float:
        """多因素适应度（越低越好）。"""
        key = tuple(indices)
        if key in self._fitness_cache:
            return self._fitness_cache[key]

        score = 0.0
        cfg = self._config

        # 1) 交通距离 + 时间 + 成本
        prev_idx = -1  # -1 表示起点
        cur_time = time_to_minutes("09:00")

        for idx in indices:
            if prev_idx >= 0:
                d, dur, cost, mode = self._matrix.lookup(
                    self._attrs[prev_idx].name, self._attrs[idx].name,
                )
                # 模式惩罚
                mode_pen = cfg.transport_mode_penalty.get(mode, 1.0)
                score += (d * 0.05 + dur * 0.02 + cost * 0.01) * mode_pen
                cur_time += int(dur) + 5  # buffer
            else:
                # 从起点出发
                d_start = self._dist_from_start(idx)
                cur_time += int(d_start * 2.5) + 5

            attr = self._attrs[idx]

            # 2) 开放时间惩罚
            open_min = time_to_minutes(attr.opening_time)
            close_min = time_to_minutes(attr.closing_time)
            if close_min <= open_min:
                close_min += 24 * 60

            if cur_time < open_min:
                # 等待开门
                wait = open_min - cur_time
                score += wait * 0.01
                cur_time = open_min

            if cur_time + attr.duration_min > close_min:
                score += cfg.opening_hours_penalty * 0.01  # scaled

            cur_time += attr.duration_min + 10  # buffer

            # 3) 必访惩罚（排越后面惩罚越大）
            if attr.must_visit:
                pos = indices.index(idx)
                score += (pos / max(self._n - 1, 1)) * 5.0

            prev_idx = idx

        # 4) 疲劳惩罚
        if self._n > 3:
            score += cfg.fatigue_penalty_per_poi * (self._n - 3)

        self._fitness_cache[key] = score
        return score

    # ------------------------------------------------------------------
    # selection / crossover / mutation
    # ------------------------------------------------------------------

    def _tournament_select(self, pop: list[list[int]]) -> list[int]:
        cfg = self._config
        k = min(cfg.tournament_size, len(pop))
        candidates = random.sample(pop, k)
        return min(candidates, key=self._fitness)

    def _ox_crossover(
        self, p1: list[int], p2: list[int]
    ) -> tuple[list[int], list[int]]:
        """Order Crossover (OX) — 保持父代相对顺序。"""
        n = len(p1)
        if n <= 2:
            return list(p1), list(p2)

        a, b = sorted(random.sample(range(n), 2))

        # child1: 从 p1 取 [a:b] 段，其余按 p2 顺序填充
        c1 = [-1] * n
        c1[a:b] = p1[a:b]
        fill = [x for x in p2 if x not in p1[a:b]]
        j = 0
        for i in range(n):
            if c1[i] == -1:
                c1[i] = fill[j]
                j += 1

        # child2: 从 p2 取 [a:b] 段
        c2 = [-1] * n
        c2[a:b] = p2[a:b]
        fill2 = [x for x in p1 if x not in p2[a:b]]
        j = 0
        for i in range(n):
            if c2[i] == -1:
                c2[i] = fill2[j]
                j += 1

        return c1, c2

    def _mutate(self, indiv: list[int]) -> list[int]:
        """复合变异：逆转变异（70%）+ 交换变异（30%）。"""
        n = len(indiv)
        if n <= 2:
            return indiv

        result = list(indiv)

        if random.random() < 0.7:
            # 逆转变异 (inversion mutation)
            a, b = sorted(random.sample(range(n), 2))
            result[a : b + 1] = reversed(result[a : b + 1])
        else:
            # 交换变异 (swap mutation)
            a, b = random.sample(range(n), 2)
            result[a], result[b] = result[b], result[a]

        return result

    # ------------------------------------------------------------------
    # feasibility
    # ------------------------------------------------------------------

    def _check_feasibility(self, indices: list[int]) -> bool:
        """检查路线是否满足所有硬约束。"""
        cur_time = time_to_minutes("09:00")

        for idx in indices:
            attr = self._attrs[idx]
            close_min = time_to_minutes(attr.closing_time)
            open_min = time_to_minutes(attr.opening_time)
            if close_min <= open_min:
                close_min += 24 * 60

            # 交通时间（从上一站）
            # 简化：用平均交通时间
            cur_time += 15  # avg transport

            if cur_time < open_min:
                cur_time = open_min

            # 如果在关门后开始 → 不可行
            if cur_time >= close_min:
                return False

            cur_time += attr.duration_min + 10

        return True

    def _collect_violations(self, indices: list[int]) -> list[str]:
        viols: list[str] = []
        cur_time = time_to_minutes("09:00")

        for idx in indices:
            attr = self._attrs[idx]
            close_min = time_to_minutes(attr.closing_time)
            open_min = time_to_minutes(attr.opening_time)
            if close_min <= open_min:
                close_min += 24 * 60

            cur_time += 15
            if cur_time < open_min:
                cur_time = open_min
            if cur_time >= close_min:
                viols.append(f"{attr.name}: closed at arrival ({cur_time // 60}:{cur_time % 60:02d})")
            cur_time += attr.duration_min + 10

        return viols

    # ------------------------------------------------------------------
    # distance helpers
    # ------------------------------------------------------------------

    def _dist_from_start(self, idx: int) -> float:
        """从起点到指定 POI 的距离。"""
        if not self._start_pos:
            return 0.0
        name = self._attrs[idx].name
        try:
            i = self._matrix.poi_names.index(name)
            # 简化：用矩阵中该 POI 到其他点的平均距离估算
            row = self._matrix.distance_km[i] if i < len(self._matrix.distance_km) else []
            return sum(row) / max(len(row), 1) if row else 3.0
        except (ValueError, IndexError):
            return 3.0

    def _dist_between(self, i: int, j: int) -> float:
        """两点间距离。"""
        d, _, _, _ = self._matrix.lookup(self._attrs[i].name, self._attrs[j].name)
        return d


# ------------------------------------------------------------------
# 便捷函数：一站式 GA-TSP 调用
# ------------------------------------------------------------------

def solve_ga_tsp(
    day_attrs: list[DayAttraction],
    transport_matrix: TransportMatrix,
    start_position: str = "",
    end_position: str | None = None,
    config: GATSPConfig | None = None,
) -> tuple[list[str], GATSPResult]:
    """一站式 GA-TSP 求解。

    Returns:
        (ordered_names, full_result)
    """
    solver = GATSPSolver(
        day_attrs=day_attrs,
        transport_matrix=transport_matrix,
        config=config,
        start_position=start_position,
        end_position=end_position,
    )
    result = solver.solve()
    return result.ordered_names, result
