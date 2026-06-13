"""蚁群算法（ACO）。"""

from __future__ import annotations

import math
import random

from src.optimizer.nearest_neighbor import nearest_neighbor_route
from src.optimizer.two_opt import two_opt


def ant_colony_optimize(
    poi_ids: list[str],
    distance_matrix: dict,
    n_ants: int = 20,
    n_iterations: int = 100,
) -> list[str]:
    """ACO 求解 TSP 路线。

    对小规模（<10 POI）自动退化为 NN + 2-opt；
    对较大规模使用完整 ACO + 2-opt 精炼。

    Args:
        poi_ids: POI ID 列表。
        distance_matrix: 距离矩阵。
        n_ants: 蚂蚁数量。
        n_iterations: 迭代次数。

    Returns:
        list[str]: 最优路线。
    """
    if len(poi_ids) <= 1:
        return list(poi_ids)

    if len(poi_ids) < 10:
        # 小规模直接用 NN + 2-opt，更快且效果相近
        nn = nearest_neighbor_route(poi_ids, distance_matrix)
        return two_opt(nn, distance_matrix)

    _dm = _build_cost_matrix(poi_ids, distance_matrix)
    n = len(poi_ids)
    pheromone = [[1.0] * n for _ in range(n)]
    best_route: list[int] | None = None
    best_cost: float = float("inf")

    alpha = 1.0   # 信息素重要度
    beta = 2.0    # 启发因子重要度
    rho = 0.1     # 挥发率
    q = 100.0     # 信息素强度

    for _ in range(n_iterations):
        for _ in range(n_ants):
            route = _construct_route(n, _dm, pheromone, alpha, beta)
            cost = _route_cost(route, _dm)
            if cost < best_cost:
                best_cost = cost
                best_route = list(route)
            # 局部信息素更新
            delta = q / (cost + 1e-9)
            for i in range(n):
                a, b = route[i], route[(i + 1) % n]
                pheromone[a][b] += delta
                pheromone[b][a] += delta

        # 全局挥发
        for i in range(n):
            for j in range(n):
                pheromone[i][j] *= (1 - rho)

    if best_route is None:
        return list(poi_ids)

    result = [poi_ids[i] for i in best_route]
    return two_opt(result, distance_matrix)


def _build_cost_matrix(poi_ids: list[str], dm: dict) -> list[list[float]]:
    """构建 n×n 成本矩阵。"""
    n = len(poi_ids)
    mat = [[float("inf")] * n for _ in range(n)]
    for i in range(n):
        mat[i][i] = 0.0
    for (a, b), v in dm.items():
        try:
            ia = poi_ids.index(str(a))
            ib = poi_ids.index(str(b))
            mat[ia][ib] = float(v)
            mat[ib][ia] = float(v)
        except ValueError:
            continue
    return mat


def _construct_route(
    n: int,
    cost: list[list[float]],
    pheromone: list[list[float]],
    alpha: float,
    beta: float,
) -> list[int]:
    """单只蚂蚁构造路线（贪心 + 概率选择）。"""
    start = random.randrange(n)
    unvisited = set(range(n))
    unvisited.discard(start)
    route = [start]

    while unvisited:
        current = route[-1]
        choices = list(unvisited)
        probs = []
        total = 0.0
        for j in choices:
            tau = pheromone[current][j] ** alpha
            eta = (1.0 / max(cost[current][j], 1e-9)) ** beta
            p = tau * eta
            probs.append(p)
            total += p

        if total > 0:
            r = random.random() * total
            cum = 0.0
            for k, p in enumerate(probs):
                cum += p
                if r <= cum:
                    nxt = choices[k]
                    break
            else:
                nxt = choices[-1]
        else:
            nxt = choices[0]

        route.append(nxt)
        unvisited.discard(nxt)

    return route


def _route_cost(route: list[int], cost: list[list[float]]) -> float:
    """计算路线总成本。"""
    total = 0.0
    n = len(route)
    for i in range(n):
        total += cost[route[i]][route[(i + 1) % n]]
    return total
