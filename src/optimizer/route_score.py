"""路线评分 — 多因素目标函数。

P2.4 Route objective: 不只看距离，同时考虑运输成本、开放时间惩罚、
用餐时间惩罚、疲劳/节奏惩罚、必访优先级。
"""

from __future__ import annotations

from typing import Any

from src.planner.plan_utils import time_to_minutes


class MultiFactorRouteScorer:
    """多因素路线评分器。

    目标函数 = w_dist  * transport_distance
             + w_cost  * transport_cost
             + w_open  * opening_hour_penalty
             + w_meal  * meal_time_penalty
             + w_fatigue * fatigue_penalty
             + w_must  * must_visit_delay_penalty
    """

    def __init__(
        self,
        distance_matrix: dict[tuple[str, str], float],
        poi_meta: dict[str, dict[str, Any]] | None = None,
        *,
        start_anchor: str = "",
        start_time: str = "09:00",
        meal_anchors: list[dict[str, Any]] | None = None,
        must_visit_names: set[str] | None = None,
        # 权重（可调）
        w_dist: float = 0.30,
        w_cost: float = 0.20,
        w_open: float = 0.20,
        w_meal: float = 0.05,
        w_fatigue: float = 0.15,
        w_must: float = 0.10,
        # 默认值
        default_open: str = "08:00",
        default_close: str = "18:00",
        default_price: float = 0.0,
        buffer_minutes: int = 15,
        max_consecutive_pois: int = 3,
    ):
        self._dm = distance_matrix
        self._poi_meta = poi_meta or {}
        self._start_anchor = start_anchor
        self._start_time = start_time
        self._meal_anchors = meal_anchors or []
        self._must_visit = must_visit_names or set()

        self.w_dist = w_dist
        self.w_cost = w_cost
        self.w_open = w_open
        self.w_meal = w_meal
        self.w_fatigue = w_fatigue
        self.w_must = w_must

        self.default_open = default_open
        self.default_close = default_close
        self.default_price = default_price
        self.buffer_minutes = buffer_minutes
        self.max_consecutive_pois = max_consecutive_pois

        # 缓存归一化参考值（首次 score 调用时计算）
        self._norm_dist: float = 1.0
        self._norm_cost: float = 1.0

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def score(self, route: list[str]) -> float:
        """计算路线总分（越低越好）。"""
        if len(route) <= 1:
            return 0.0

        dist = self._transport_distance(route)
        cost = self._transport_cost(route)
        open_p = self._opening_penalty(route)
        meal_p = self._meal_penalty(route)
        fatigue_p = self._fatigue_penalty(route)
        must_p = self._must_visit_penalty(route)

        # 首调用时用实际值归一化
        if self._norm_dist == 1.0 and dist > 0:
            self._norm_dist = max(dist, 0.1)
        if self._norm_cost == 1.0 and cost > 0:
            self._norm_cost = max(cost, 0.1)

        return (
            self.w_dist * (dist / self._norm_dist)
            + self.w_cost * (cost / self._norm_cost)
            + self.w_open * open_p
            + self.w_meal * meal_p
            + self.w_fatigue * fatigue_p
            + self.w_must * must_p
        )

    def score_pair(self, a: str, b: str) -> float:
        """两点间的边代价。"""
        dist = self._lookup(a, b)
        cost_val = self._transport_cost_for(a, b)
        # 简单归一化
        return 0.5 * (dist / max(self._norm_dist, 0.1)) + 0.5 * (cost_val / max(self._norm_cost, 0.1))

    # ------------------------------------------------------------------
    # component calculations
    # ------------------------------------------------------------------

    def _transport_distance(self, route: list[str]) -> float:
        total = 0.0
        prev = self._start_anchor
        for name in route:
            if prev:
                total += self._lookup(prev, name)
            prev = name
        return total

    def _transport_cost(self, route: list[str]) -> float:
        total = 0.0
        prev = self._start_anchor
        for name in route:
            if prev:
                total += self._transport_cost_for(prev, name)
            prev = name
        return total

    def _opening_penalty(self, route: list[str]) -> float:
        """累计开放时间惩罚（归一化 0-1）。"""
        penalty = 0.0
        cur_min = time_to_minutes(self._start_time)
        prev = self._start_anchor

        for name in route:
            # 运输时间
            travel = self._lookup(prev, name) if prev else 0.0
            cur_min += int(travel)

            meta = self._meta_for(name)
            open_t = meta.get("opentime", self.default_open)
            close_t = meta.get("endtime", self.default_close)

            open_min = time_to_minutes(open_t) if open_t else 0
            close_min = time_to_minutes(close_t) if close_t else 24 * 60
            if close_min <= open_min:
                close_min += 24 * 60  # overnight

            # 到达太早 → 等待惩罚（按等待分钟比例）
            if cur_min < open_min:
                wait = open_min - cur_min
                penalty += min(1.0, wait / 120.0)  # cap at 2 hours
                cur_min = open_min

            # 到达太晚（已关门或接近关门）→ 关门惩罚
            visit_dur = int(meta.get("recommendmintime", 1.5) * 60)
            if cur_min + visit_dur > close_min:
                overlap = (cur_min + visit_dur) - close_min
                penalty += min(2.0, overlap / 60.0)  # cap at 1 hour overlap

            # 前进
            cur_min += visit_dur + self.buffer_minutes
            prev = name

        return penalty

    def _meal_penalty(self, route: list[str]) -> float:
        """累计用餐冲突惩罚。"""
        if not self._meal_anchors:
            return 0.0

        penalty = 0.0
        cur_min = time_to_minutes(self._start_time)
        prev = self._start_anchor

        for i, name in enumerate(route):
            travel = self._lookup(prev, name) if prev else 0.0
            cur_min += int(travel)

            meta = self._meta_for(name)
            visit_dur = int(meta.get("recommendmintime", 1.5) * 60)

            # 检查每个用餐锚点是否被挤压
            for meal in self._meal_anchors:
                meal_start = time_to_minutes(meal.get("start", "12:00"))
                meal_end = time_to_minutes(meal.get("end", "13:00"))
                # 活动跨越用餐窗口
                act_end = cur_min + visit_dur
                if cur_min < meal_end and act_end > meal_start:
                    # 冲突量：重叠分钟数
                    overlap = min(act_end, meal_end) - max(cur_min, meal_start)
                    if overlap > 30:  # >30min 重叠算显著冲突
                        penalty += overlap / 60.0

            cur_min += visit_dur + self.buffer_minutes
            prev = name

        return penalty

    def _fatigue_penalty(self, route: list[str]) -> float:
        """疲劳惩罚：连续多个景点没有足够休息。"""
        if len(route) <= self.max_consecutive_pois:
            return 0.0

        penalty = 0.0
        consecutive = 0
        prev = self._start_anchor

        for name in route:
            travel = self._lookup(prev, name) if prev else 0.0
            # 长距离移动算作休息
            if travel > 30:  # >30 min travel time counts as rest
                consecutive = 0
            else:
                consecutive += 1

            if consecutive > self.max_consecutive_pois:
                penalty += (consecutive - self.max_consecutive_pois) * 0.15

            prev = name

        return penalty

    def _must_visit_penalty(self, route: list[str]) -> float:
        """必访景点排在后面 → 惩罚。"""
        if not self._must_visit:
            return 0.0

        penalty = 0.0
        n = len(route)
        for i, name in enumerate(route):
            if name in self._must_visit or self._is_must_visit_fuzzy(name):
                # 排在越后面惩罚越大（线性衰减）
                position_ratio = i / max(n - 1, 1)
                penalty += position_ratio  # 0 if first, 1 if last

        return penalty

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _lookup(self, a: str, b: str) -> float:
        if not a or not b or a == b:
            return 0.0
        val = self._dm.get((a, b))
        if val is not None:
            return float(val)
        val = self._dm.get((b, a))
        if val is not None:
            return float(val)
        # fuzzy
        for (ka, kb), v in self._dm.items():
            if (str(a) in str(ka) and str(b) in str(kb)) or (str(a) in str(kb) and str(b) in str(ka)):
                return float(v)
        return 3.0  # default 3 km

    def _transport_cost_for(self, a: str, b: str) -> float:
        """两点间预估运输成本（元）。"""
        dist = self._lookup(a, b)
        # 简单模型：地铁 ~0.3 元/km，出租 ~2 元/km
        if dist < 1.0:
            return 0.0  # walk
        elif dist < 5.0:
            return dist * 0.4  # metro-ish
        else:
            return dist * 1.5  # taxi-ish

    def _meta_for(self, name: str) -> dict[str, Any]:
        """获取 POI 的 metadata（模糊匹配）。"""
        if name in self._poi_meta:
            return self._poi_meta[name]
        name_l = name.lower()
        for key, meta in self._poi_meta.items():
            if name_l in key.lower() or key.lower() in name_l:
                return meta
        return {}

    def _is_must_visit_fuzzy(self, name: str) -> bool:
        name_l = name.lower()
        for mv in self._must_visit:
            if mv.lower() in name_l or name_l in mv.lower():
                return True
        return False


# ------------------------------------------------------------------
# backward-compatible simple scorer (P1 behavior)
# ------------------------------------------------------------------

def score_route(route: list[str], distance_matrix: dict[tuple[str, str], float]) -> float:
    """简单距离评分（向后兼容）。"""
    if len(route) <= 1:
        return 0.0

    total = 0.0
    for i in range(len(route) - 1):
        key = (route[i], route[i + 1])
        val = distance_matrix.get(key)
        if val is None:
            val = _fuzzy_lookup(route[i], route[i + 1], distance_matrix)
        if val is None:
            val = float("inf")
        total += float(val)

    return total


def _fuzzy_lookup(a: str, b: str, dm: dict) -> float | None:
    for (ka, kb), v in dm.items():
        if (str(ka) == str(a) and str(kb) == str(b)) or (
            str(ka) in str(a) and str(kb) in str(b)
        ):
            return float(v)
    return None
