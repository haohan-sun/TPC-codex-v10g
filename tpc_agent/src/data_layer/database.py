"""官方旅行沙盒数据访问层。"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.data_layer.paths import get_project_root, resolve_data_path


# POI 类别与文件名映射（对接 data/raw/sandbox/ 目录结构）
POI_CATEGORIES = {
    "attraction": "attractions",
    "restaurant": "restaurants",
    "hotel": "hotels",
    "accommodation": "hotels",
}


class TravelDatabase:
    """旅行沙盒数据库：按城市加载 POI 并提供检索接口。

    期望的 raw 目录结构（二选一，自动探测）：

    方案 A（按类别分文件）::
        data/raw/sandbox/attractions/北京.json
        data/raw/sandbox/restaurants/北京.json

    方案 B（按城市分目录）::
        data/raw/sandbox/北京/attractions.json
    """

    def __init__(self, sandbox_root: str | Path | None = None) -> None:
        """初始化数据库。

        Args:
            sandbox_root: 沙盒根目录；为 None 时从 config.yaml 读取。
        """
        if sandbox_root is None:
            self.sandbox_root = resolve_data_path("data_raw", "data/raw") / "sandbox"
        else:
            self.sandbox_root = Path(sandbox_root)

        # 内存缓存：city -> category -> list[record]
        self._cache: dict[str, dict[str, list[dict[str, Any]]]] = {}

    def _normalize_city(self, city: str) -> str:
        """标准化城市名（去首尾空格）。"""
        return city.strip()

    def _load_category_file(self, path: Path) -> list[dict[str, Any]]:
        """读取单个 JSON 文件，兼容 list 或 {\"data\": [...]} 格式。"""
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("data", "items", "pois", "records"):
                if isinstance(payload.get(key), list):
                    return payload[key]
        return []

    def _resolve_category_path(self, city: str, category: str) -> Path:
        """解析某城市某类别数据文件路径。"""
        city = self._normalize_city(city)
        folder = POI_CATEGORIES.get(category, category)

        # 方案 A: sandbox/attractions/北京.json
        path_a = self.sandbox_root / folder / f"{city}.json"
        if path_a.exists():
            return path_a

        # 方案 B: sandbox/北京/attractions.json
        path_b = self.sandbox_root / city / f"{folder}.json"
        if path_b.exists():
            return path_b

        # 回退：尝试英文/拼音文件名（兼容部分官方包）
        path_c = self.sandbox_root / folder / f"{city.lower()}.json"
        return path_c if path_c.exists() else path_a

    def load_city_category(self, city: str, category: str) -> list[dict[str, Any]]:
        """加载指定城市、指定类别的 POI 列表（带缓存）。"""
        city = self._normalize_city(city)
        if city not in self._cache:
            self._cache[city] = {}
        if category in self._cache[city]:
            return self._cache[city][category]

        # 优先 ChinaTravel CSV
        try:
            from src.data_layer.chinatravel_bridge import load_csv_records

            ct_records = load_csv_records(city, category)
            if ct_records:
                self._cache[city][category] = ct_records
                return ct_records
        except Exception:
            pass

        file_path = self._resolve_category_path(city, category)
        records = self._load_category_file(file_path)
        self._cache[city][category] = records
        return records

    def get_poi_by_id(self, poi_id: str, city: str | None = None) -> dict[str, Any]:
        """按 ID 查询 POI 详情。

        Args:
            poi_id: POI 标识（id / poi_id / name 字段均可匹配）。
            city: 可选，限定搜索城市以加速。

        Returns:
            dict: POI 详情；未找到时返回空 dict。
        """
        cities = [city] if city else list(self._cache.keys())
        if not cities:
            # 尚未加载任何城市，尝试扫描 sandbox 目录下的城市文件
            cities = self._discover_cities()

        for c in cities:
            if not c:
                continue
            for category in POI_CATEGORIES:
                for record in self.load_city_category(c, category):
                    if self._match_poi_id(record, poi_id):
                        enriched = dict(record)
                        enriched.setdefault("city", c)
                        enriched.setdefault("category", category)
                        return enriched
        return {}

    def _discover_cities(self) -> list[str]:
        """从 sandbox 目录结构推断可用城市名。"""
        cities: set[str] = set()
        if not self.sandbox_root.exists():
            return []

        for sub in self.sandbox_root.iterdir():
            if sub.is_dir() and not sub.name.startswith("."):
                cities.add(sub.name)
            elif sub.is_file() and sub.suffix == ".json":
                cities.add(sub.stem)
        return sorted(cities)

    @staticmethod
    def _match_poi_id(record: dict[str, Any], poi_id: str) -> bool:
        """判断记录是否匹配给定 POI ID。"""
        poi_id = str(poi_id)
        for key in ("id", "poi_id", "uid", "name"):
            if str(record.get(key, "")) == poi_id:
                return True
        return False

    def search_pois(
        self,
        city: str,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """按城市与过滤条件搜索 POI。

        Args:
            city: 目标城市。
            filters: 可选过滤项，支持：
                - category: attraction / restaurant / hotel
                - name_contains: 名称子串
                - max_price: 最高单价
                - min_price: 最低单价

        Returns:
            list[dict]: 匹配的 POI 列表。
        """
        filters = filters or {}
        category = filters.get("category")
        categories = [category] if category else list(POI_CATEGORIES.keys())

        results: list[dict[str, Any]] = []
        for cat in categories:
            for record in self.load_city_category(city, cat):
                if not self._apply_filters(record, filters):
                    continue
                item = dict(record)
                item.setdefault("city", self._normalize_city(city))
                item.setdefault("category", cat)
                results.append(item)
        return results

    @staticmethod
    def _apply_filters(record: dict[str, Any], filters: dict[str, Any]) -> bool:
        """对单条 POI 记录应用过滤条件。"""
        name = str(record.get("name", ""))
        if filters.get("name_contains") and filters["name_contains"] not in name:
            return False

        price = record.get("price") or record.get("cost") or record.get("avg_price")
        if price is not None:
            try:
                price_val = float(price)
                if "max_price" in filters and price_val > float(filters["max_price"]):
                    return False
                if "min_price" in filters and price_val < float(filters["min_price"]):
                    return False
            except (TypeError, ValueError):
                pass
        return True

    @staticmethod
    def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """计算两点球面距离（公里）。"""
        r = 6371.0
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        d_phi = math.radians(lat2 - lat1)
        d_lambda = math.radians(lon2 - lon1)
        a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
        return 2 * r * math.asin(math.sqrt(a))

    def get_transport_matrix(self, poi_ids: list[str], city: str | None = None) -> dict[str, Any]:
        """获取 POI 间交通时间与距离矩阵。

        若 sandbox 中无预计算矩阵，则根据 POI 经纬度估算直线距离，
        并按 25 km/h 估算市内通行时间（分钟）。

        Args:
            poi_ids: POI ID 列表。
            city: 可选城市，加速 POI 定位。

        Returns:
            dict: {
                "poi_ids": [...],
                "distance_km": [[...]],
                "duration_min": [[...]],
            }
        """
        poi_records: list[dict[str, Any]] = []
        for pid in poi_ids:
            record = self.get_poi_by_id(pid, city=city)
            poi_records.append(record)

        n = len(poi_ids)
        distance = [[0.0] * n for _ in range(n)]
        duration = [[0.0] * n for _ in range(n)]

        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                dist = self._estimate_distance(poi_records[i], poi_records[j])
                distance[i][j] = dist
                duration[i][j] = dist / 25.0 * 60.0  # 25km/h -> 分钟

        return {
            "poi_ids": poi_ids,
            "distance_km": distance,
            "duration_min": duration,
            "city": city,
        }

    @staticmethod
    def _estimate_distance(a: dict[str, Any], b: dict[str, Any]) -> float:
        """估算两 POI 间距离；无坐标时返回默认值 3km。"""
        def _coords(rec: dict[str, Any]) -> tuple[float, float] | None:
            if "latitude" in rec and "longitude" in rec:
                return float(rec["latitude"]), float(rec["longitude"])
            if "lat" in rec and "lng" in rec:
                return float(rec["lat"]), float(rec["lng"])
            loc = rec.get("location")
            if isinstance(loc, dict):
                if "lat" in loc and "lng" in loc:
                    return float(loc["lat"]), float(loc["lng"])
            return None

        ca, cb = _coords(a), _coords(b)
        if ca and cb:
            return TravelDatabase._haversine_km(ca[0], ca[1], cb[0], cb[1])
        return 3.0


# 模块级默认实例，供简单调用
_default_db: TravelDatabase | None = None


def get_database() -> TravelDatabase:
    """获取全局 TravelDatabase 单例。"""
    global _default_db
    if _default_db is None:
        _default_db = TravelDatabase()
    return _default_db


def get_poi_by_id(poi_id: str, city: str | None = None) -> dict[str, Any]:
    """模块级快捷函数：按 ID 查询 POI。"""
    return get_database().get_poi_by_id(poi_id, city=city)


def search_pois(city: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """模块级快捷函数：搜索 POI。"""
    return get_database().search_pois(city, filters=filters)


def get_transport_matrix(poi_ids: list[str], city: str | None = None) -> dict[str, Any]:
    """模块级快捷函数：获取交通矩阵。"""
    return get_database().get_transport_matrix(poi_ids, city=city)
