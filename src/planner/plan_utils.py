"""规划工具：时间计算、activity 构建。"""

from __future__ import annotations

import re
import warnings
from typing import Any

# 官方 schema 要求 start_time/end_time 必须是 HH:MM（两位小时）
_TIME_PATTERN = re.compile(r"^\d{2}:\d{2}$")
_MAX_MINUTES = 24 * 60  # 一天最大分钟数


def _validate_time_format(time_str: str, context: str = "") -> None:
    """校验时间格式是否为 HH:MM；三位数小时会触发 RuntimeError（fail fast）。"""
    if not _TIME_PATTERN.match(time_str):
        msg = f"时间格式违规: {time_str!r}"
        if context:
            msg = f"{msg} ({context})"
        raise RuntimeError(msg)


def is_valid_time_format(time_str: str) -> bool:
    """返回时间字符串是否符合 ^\\d{2}:\\d{2}$ schema。"""
    return bool(_TIME_PATTERN.match(time_str))


def add_minutes(time_str: str, minutes: int, *, allow_overflow: bool = False) -> str:
    """HH:MM 加分钟。

    Args:
        time_str: 起始时间（HH:MM）。
        minutes: 增加的分钟数（可为负）。
        allow_overflow: True 时允许跨过 23:59（城际交通专用）；默认 False 时
            超过 23:59 会抛出 RuntimeError（不在底层吞掉排程错误）。
    """
    try:
        h, m = map(int, time_str.split(":"))
    except (ValueError, AttributeError):
        raise ValueError(f"add_minutes: 无法解析时间 {time_str!r}") from None
    total = h * 60 + m + minutes
    if total >= _MAX_MINUTES:
        if allow_overflow:
            return f"{total // 60:02d}:{total % 60:02d}"
        raise RuntimeError(
            f"排程不可行: {time_str} + {minutes}min = "
            f"{total // 60:02d}:{total % 60:02d} 超出当天 23:59"
        )
    if total < 0:
        raise RuntimeError(f"排程不可行: {time_str} + {minutes}min = 负时间")
    return f"{total // 60:02d}:{total % 60:02d}"


def time_to_minutes(time_str: str) -> int:
    h, m = map(int, time_str.split(":"))
    return h * 60 + m


def minutes_to_time(total: int) -> str:
    total = max(0, total)
    return f"{total // 60:02d}:{total % 60:02d}"


def max_time(a: str, b: str) -> str:
    return a if time_to_minutes(a) >= time_to_minutes(b) else b


def annotate_transports(
    segments: list[dict[str, Any]],
    people: int,
    taxi_cars: int | None = None,
) -> list[dict[str, Any]]:
    """补全官方 transport 字段：price=单价, cost=单价*tickets/cars, tickets/cars。"""
    cars = taxi_cars if taxi_cars is not None else max(1, (people + 3) // 4)
    result: list[dict[str, Any]] = []
    for seg in segments:
        item = dict(seg)
        item.setdefault("distance", item.get("distance", 0.0))
        mode = item.get("mode", "")
        # per-unit price
        unit_price = float(item.get("price", item.get("cost", 0)))
        if mode == "metro":
            item["tickets"] = people
            item["price"] = unit_price
            item["cost"] = round(unit_price * people, 2)
        elif mode == "taxi":
            item["cars"] = cars
            item["price"] = unit_price
            item["cost"] = round(unit_price * cars, 2)
        else:  # walk
            item["price"] = 0.0
            item["cost"] = 0.0
        result.append(item)
    return result


def empty_transports() -> list[dict[str, Any]]:
    """空交通列表（满足 schema required）。"""
    return []


def make_activity(
    act_type: str,
    start_time: str,
    end_time: str,
    cost: float,
    price: float,
    transports: list[dict] | None = None,
    position: str = "",
    tickets: int = 1,
    extra: dict | None = None,
) -> dict[str, Any]:
    """构建单条官方 activity 字典。"""
    act: dict[str, Any] = {
        "type": act_type,
        "start_time": start_time,
        "end_time": end_time,
        "cost": round(float(cost), 2),
        "price": round(float(price), 2),
        "transports": transports if transports is not None else empty_transports(),
    }
    if position:
        act["position"] = position
    if act_type in ("attraction", "airplane", "train"):
        act["tickets"] = tickets
    if extra:
        act.update(extra)
    return act


def make_intercity_activity(row: dict, people: int, is_return: bool = False) -> dict[str, Any]:
    """从城际交通记录构建 airplane/train activity。"""
    mode = row.get("type", "airplane")
    start = row.get("From") or row.get("start") or row.get("start_city", "")
    end = row.get("To") or row.get("end") or row.get("target_city", "")
    start_time = row.get("BeginTime") or row.get("start_time") or "08:00"
    end_time = row.get("EndTime") or row.get("end_time") or "10:30"
    unit_price = float(row.get("Price") or row.get("Cost") or row.get("price") or 500)
    total_cost = unit_price * people

    extra: dict[str, Any] = {"start": start, "end": end}
    if mode == "airplane":
        fid = row.get("FlightID") or row.get("FlightId") or ""
        if not fid:
            raise ValueError(f"城际航班缺少 FlightID: {start}->{end}，拒绝伪造")
        extra["FlightID"] = str(fid)
    else:
        tid = row.get("TrainID") or row.get("TrainId") or ""
        if not tid:
            raise ValueError(f"城际火车缺少 TrainID: {start}->{end}，拒绝伪造")
        extra["TrainID"] = str(tid)

    return make_activity(
        act_type=mode,
        start_time=start_time,
        end_time=end_time,
        cost=total_cost,
        price=unit_price,
        tickets=people,
        transports=empty_transports(),
        extra=extra,
    )


def normalize_transports(segments: list[dict], people: int = 1, taxi_cars: int | None = None) -> list[dict]:
    """补全 transport 段的 price/tickets/cars 字段。"""
    return annotate_transports(segments, people, taxi_cars)
