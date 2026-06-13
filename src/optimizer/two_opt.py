"""2-opt 局部搜索 — 支持简单距离和多因素评分。"""

from __future__ import annotations

from typing import Callable

from src.optimizer.route_score import score_route


def two_opt(
    route: list[str],
    distance_matrix: dict,
    scorer: Callable[[list[str]], float] | None = None,
) -> list[str]:
    """2-opt 优化路线。

    Args:
        route: 当前路线（有序 POI ID 列表）。
        distance_matrix: 距离矩阵。
        scorer: 可选的多因素评分函数 route -> float（越低越好）。
                若为 None 则使用简单距离评分。

    Returns:
        list[str]: 优化后路线。
    """
    if len(route) <= 2:
        return list(route)

    _dm = _to_tuple_dict(distance_matrix)
    best = list(route)

    if scorer is not None:
        best_score = scorer(best)
    else:
        best_score = score_route(best, _dm)

    improved = True
    while improved:
        improved = False
        for i in range(len(best) - 1):
            for j in range(i + 2, len(best)):
                new_route = best[: i + 1] + best[i + 1 : j + 1][::-1] + best[j + 1 :]
                if scorer is not None:
                    new_score = scorer(new_route)
                else:
                    new_score = score_route(new_route, _dm)
                if new_score < best_score:
                    best = new_route
                    best_score = new_score
                    improved = True
                    break
            if improved:
                break

    return best


def _to_tuple_dict(dm: dict) -> dict[tuple[str, str], float]:
    """统一距离矩阵格式。"""
    out: dict[tuple[str, str], float] = {}
    for k, v in dm.items():
        if isinstance(k, tuple) and len(k) == 2:
            out[(str(k[0]), str(k[1]))] = float(v)
        elif isinstance(k, str):
            parts = k.split("->")
            if len(parts) == 2:
                out[(parts[0].strip(), parts[1].strip())] = float(v)
    return out
