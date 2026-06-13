"""ChinaTravel WorldEnv 客户端：agent_env / direct WorldEnv / CSV 三层后端。

后端优先级（可通过 config 配置）:
    1. agent_env.adapter.ChinaTravelEnvAdapter  （结构化工具调用）
    2. direct chinatravel.environment.world_env.WorldEnv
    3. CSV bridge fallback（chinatravel_bridge → database）
"""

from __future__ import annotations

from typing import Any

from src.data_layer.chinatravel_bridge import (
    get_world_env,
    infer_lang,
    is_chinatravel_database_ready,
    load_csv_records,
    resolve_chinatravel_root,
)
from src.data_layer.database import get_database
from src.data_layer.paths import load_project_config
from src.data_layer.schema import POICandidate
from src.planner.plan_utils import add_minutes, annotate_transports, time_to_minutes


# 城市名英→中转換（用于城际交通 JSON 文件查找）
_ENG_TO_ZH = {
    "beijing": "北京", "shanghai": "上海", "nanjing": "南京",
    "suzhou": "苏州", "hangzhou": "杭州", "shenzhen": "深圳",
    "chengdu": "成都", "wuhan": "武汉", "guangzhou": "广州", "chongqing": "重庆",
}
_ENG_TO_ZH.update({k.capitalize(): v for k, v in _ENG_TO_ZH.items()})
_ENG_TO_ZH.update({k.upper(): v for k, v in _ENG_TO_ZH.items()})


def _eng_to_zh(city: str) -> str | None:
    """英文城市名 → 中文城市名；已是中文则直接返回。"""
    if any("一" <= ch <= "鿿" for ch in city):
        return city
    return _ENG_TO_ZH.get(city) or _ENG_TO_ZH.get(city.lower())


# ---------------------------------------------------------------------------
# agent_env backend
# ---------------------------------------------------------------------------

class AgentEnvBackend:
    """封装 agent_env.adapter.ChinaTravelEnvAdapter。

    将 ``{success, data, command, text}`` 包装统一拆解，
    使 SandboxClient 可以从 agent_env 和 direct WorldEnv 无差别读取。
    """

    def __init__(self, agent_env_cwd: str | None = None) -> None:
        self._adapter = None
        self._agent_env_cwd = agent_env_cwd or "ChinaTravel"

    @property
    def adapter(self):
        if self._adapter is None:
            import sys
            from pathlib import Path

            cwd_path = Path(self._agent_env_cwd)
            if not cwd_path.is_absolute():
                # relative to project root
                from src.data_layer.paths import get_project_root

                cwd_path = get_project_root() / cwd_path
            cwd_str = str(cwd_path.resolve())
            if cwd_str not in sys.path:
                sys.path.insert(0, cwd_str)

            from agent_env.adapter import ChinaTravelEnvAdapter

            self._adapter = ChinaTravelEnvAdapter()
        return self._adapter

    @property
    def available(self) -> bool:
        try:
            _ = self.adapter
            return True
        except Exception:
            return False

    def _call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """调用 agent_env tool；失败返回 {"success": False, "data": None}。"""
        try:
            result = self.adapter.call_tool(tool_name, arguments)
        except Exception as exc:
            return {"success": False, "error": str(exc), "data": None}
        if not result.get("success"):
            return {"success": False, "error": result.get("error", "unknown"), "data": result.get("data")}
        return {"success": True, "data": result.get("data")}

    # -- normalized tool wrappers (return same shapes as direct WorldEnv) --

    def goto(
        self, city: str, start: str, end: str, start_time: str, mode: str = "metro"
    ) -> list[dict[str, Any]]:
        r = self._call("goto", {
            "city": city,
            "start": start,
            "end": end,
            "start_time": start_time,
            "transport_type": mode,
        })
        if not r["success"]:
            return []
        data = r["data"]
        if isinstance(data, list):
            return _normalize_goto_segments(data)
        return []

    def intercity_transport_select(
        self, start_city: str, end_city: str, mode: str, earliest_leave_time: str = "06:00",
    ) -> list[dict[str, Any]]:
        r = self._call("intercity_transport_select", {
            "start_city": start_city,
            "end_city": end_city,
            "intercity_type": mode,
            "earliest_leave_time": earliest_leave_time,
        })
        if not r["success"]:
            return []
        return _normalize_dataframe_rows(r["data"])

    def attractions_nearby(
        self, city: str, point: str, topk: int = 10, max_dist_km: float = 5.0,
    ) -> list[dict[str, Any]]:
        r = self._call("attractions_nearby", {
            "city": city, "point": point, "topk": topk, "dist": max_dist_km,
        })
        if not r["success"]:
            return []
        return _normalize_dataframe_rows(r["data"])

    def accommodations_nearby(
        self, city: str, anchor: str, topk: int = 10, max_dist_km: float = 8.0,
    ) -> list[dict[str, Any]]:
        r = self._call("accommodations_nearby", {
            "city": city, "point": anchor, "topk": topk, "dist": max_dist_km,
        })
        if not r["success"]:
            return []
        return _normalize_dataframe_rows(r["data"])

    def restaurants_nearby(
        self, city: str, point: str, topk: int = 10, max_dist_km: float = 5.0,
    ) -> list[dict[str, Any]]:
        r = self._call("restaurants_nearby", {
            "city": city, "point": point, "topk": topk, "dist": max_dist_km,
        })
        if not r["success"]:
            return []
        return _normalize_dataframe_rows(r["data"])

    def poi_lat_lon(self, city: str, name: str) -> dict[str, Any] | None:
        r = self._call("poi_lat_lon_search", {"city": city, "name": name})
        if not r["success"]:
            return None
        data = r["data"]
        if isinstance(data, (list, tuple)) and len(data) >= 2:
            return {"lat": float(data[0]), "lon": float(data[1])}
        return None

    def select_attractions(self, city: str, key: str, op: str, value: Any) -> list[dict[str, Any]]:
        r = self._call("attractions_select", {"city": city, "key": key, "op": op, "value": value})
        if not r["success"]:
            return []
        return _normalize_dataframe_rows(r["data"])

    def select_accommodations(self, city: str, key: str, op: str, value: Any) -> list[dict[str, Any]]:
        r = self._call("accommodations_select", {"city": city, "key": key, "op": op, "value": value})
        if not r["success"]:
            return []
        return _normalize_dataframe_rows(r["data"])

    def select_restaurants(self, city: str, key: str, op: str, value: Any) -> list[dict[str, Any]]:
        r = self._call("restaurants_select", {"city": city, "key": key, "op": op, "value": value})
        if not r["success"]:
            return []
        return _normalize_dataframe_rows(r["data"])

    def is_attraction_open(self, city: str, poi_id: int, time_str: str) -> bool:
        r = self._call("attractions_id_is_open", {"city": city, "id": poi_id, "time": time_str})
        if not r["success"]:
            return True  # fallback: assume open
        return bool(r["data"])

    def is_restaurant_open(self, city: str, poi_id: int, time_str: str) -> bool:
        r = self._call("restaurants_id_is_open", {"city": city, "id": poi_id, "time": time_str})
        if not r["success"]:
            return True
        return bool(r["data"])


# ---------------------------------------------------------------------------
# normalize helpers — unify agent_env / direct / CSV output shapes
# ---------------------------------------------------------------------------

def _normalize_goto_segments(data: Any) -> list[dict[str, Any]]:
    """Normalize goto output to list of segment dicts.

    agent_env returns::
        [{"start":..., "end":..., "mode":..., "start_time":..., "end_time":..., "cost":..., "distance":...}]

    WorldEnv direct returns the same shape.
    """
    if not isinstance(data, list):
        return []
    segments: list[dict[str, Any]] = []
    for seg in data:
        if not isinstance(seg, dict):
            continue
        segments.append({
            "start": str(seg.get("start", "")),
            "end": str(seg.get("end", "")),
            "mode": str(seg.get("mode", "walk")),
            "start_time": str(seg.get("start_time", "")),
            "end_time": str(seg.get("end_time", "")),
            "cost": float(seg.get("cost", 0)),
            "price": float(seg.get("cost", 0)),   # alias for budget calc
            "distance": float(seg.get("distance", 0)),
        })
    return segments


def _normalize_dataframe_rows(data: Any) -> list[dict[str, Any]]:
    """Normalize agent_env dataframe wrapper or direct list to list[dict].

    agent_env wraps DataFrame results as::
        {"type": "dataframe", "columns": [...], "rows": [{...}, ...]}

    Direct WorldEnv returns a DataFrame (handled by _df_to_records).
    """
    if data is None:
        return []
    if isinstance(data, list):
        # already a list of dicts
        return [dict(r) for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        if data.get("type") == "dataframe":
            rows = data.get("rows")
            if isinstance(rows, list):
                return [dict(r) for r in rows if isinstance(r, dict)]
        # maybe a single record
        return [dict(data)]
    return []


def _normalize_intercity_row(row: dict[str, Any], mode: str) -> dict[str, Any]:
    """Normalize a single intercity transport row to the format plan_builder expects.

    agent_env fields: TrainID/FlightID, From, To, BeginTime, EndTime, Cost/Duration, etc.
    """
    out = dict(row)
    out.setdefault("type", mode)
    # unify field aliases
    if "From" in out and "start" not in out:
        out["start"] = out["From"]
    if "To" in out and "end" not in out:
        out["end"] = out["To"]
    if "BeginTime" in out and "start_time" not in out:
        out["start_time"] = out["BeginTime"]
    if "EndTime" in out and "end_time" not in out:
        out["end_time"] = out["EndTime"]
    if "Cost" in out and "Price" not in out:
        out["Price"] = out["Cost"]
    # normalize IDs（从真实数据取值，不伪造）
    if mode == "train":
        out["TrainID"] = str(out.get("TrainID", out.get("id", "")))
    if mode == "airplane":
        out["FlightID"] = str(out.get("FlightID", out.get("id", "")))
    return out


# ---------------------------------------------------------------------------
# helpers (unchanged)
# ---------------------------------------------------------------------------

def _df_to_records(df: Any) -> list[dict[str, Any]]:
    if df is None:
        return []
    if hasattr(df, "empty") and df.empty:
        return []
    if hasattr(df, "to_dict"):
        return df.to_dict(orient="records")
    if isinstance(df, list):
        return df
    return []


def _record_to_candidate(record: dict[str, Any]) -> POICandidate:
    poi_id = str(record.get("id", record.get("name", "")))
    return POICandidate(
        poi_id=poi_id,
        name=str(record.get("name", "")),
        metadata=record,
    )


def _resolve_backend(config_backend: str, agent_env_cwd: str) -> str:
    """Resolve 'auto' to the first available backend."""
    if config_backend != "auto":
        return config_backend
    # try agent_env first
    try:
        backend = AgentEnvBackend(agent_env_cwd=agent_env_cwd)
        if backend.available:
            return "agent_env"
    except Exception:
        pass
    # try direct WorldEnv
    env = get_world_env("en")
    if env is not None:
        return "direct"
    return "csv"


class SandboxClient:
    """统一沙盒访问：agent_env → direct WorldEnv → CSV/JSON database 兜底。

    通过 config.yaml 中 ``world_env.backend`` 控制后端选择:
        - auto      依次尝试 agent_env → direct → csv
        - agent_env 仅 agent_env + csv fallback
        - direct    仅 direct WorldEnv + csv fallback
        - csv       仅 csv/json

    内置请求级缓存：go_to / poi_distance / is_*_open 等高频调用在同一
    query 内自动去重，大幅降低 agent_env / WorldEnv 往返次数。
    """

    def __init__(self, lang: str | None = None) -> None:
        self.lang = lang or "en"
        config = load_project_config()
        we_config = config.get("world_env", {}) if config else {}
        backend_name = we_config.get("backend", "auto")
        agent_env_cwd = we_config.get("agent_env_cwd", "ChinaTravel")
        self._backend_name = _resolve_backend(backend_name, agent_env_cwd)

        # agent_env backend (lazy init on first use)
        self._agent_env: AgentEnvBackend | None = None
        if self._backend_name in ("agent_env",):
            try:
                self._agent_env = AgentEnvBackend(agent_env_cwd=agent_env_cwd)
            except Exception:
                pass

        # direct WorldEnv
        self._env = get_world_env(self.lang) if self._backend_name in ("agent_env", "direct") else None

        # CSV / JSON database (always available as fallback)
        self._db = get_database()

        # 请求级缓存：避免同一次 query 中重复查询同一 POI 的 distance/open 等
        self._cache_goto: dict[tuple, list[dict[str, Any]]] = {}
        self._cache_distance: dict[tuple, float | None] = {}
        self._cache_attraction_open: dict[tuple, bool] = {}
        self._cache_restaurant_open: dict[tuple, bool] = {}
        self._cache_list_attractions: dict[str, list[dict[str, Any]]] = {}
        self._cache_list_restaurants: dict[str, list[dict[str, Any]]] = {}
        self._cache_list_hotels: dict[str, list[dict[str, Any]]] = {}

    def clear_caches(self) -> None:
        """清空请求级缓存（每次新 query 开始时调用）。"""
        self._cache_goto.clear()
        self._cache_distance.clear()
        self._cache_attraction_open.clear()
        self._cache_restaurant_open.clear()
        self._cache_list_attractions.clear()
        self._cache_list_restaurants.clear()
        self._cache_list_hotels.clear()

    @property
    def has_world_env(self) -> bool:
        return self._env is not None or self._agent_env is not None

    @property
    def database_ready(self) -> bool:
        return is_chinatravel_database_ready(self.lang)

    @property
    def backend_name(self) -> str:
        return self._backend_name

    # ------------------------------------------------------------------
    # list_*  — 全量列表（用于候选池构建）
    # ------------------------------------------------------------------

    def list_attractions(self, city: str, limit: int = 50) -> list[dict[str, Any]]:
        cache_key = f"{city}:{limit}"
        if cache_key in self._cache_list_attractions:
            return self._cache_list_attractions[cache_key]
        # agent_env: use select with key="name", op="ne", value="" (matches all)
        if self._agent_env:
            try:
                records = self._agent_env.select_attractions(city, "name", "ne", "")
                if records:
                    result = records[:limit]
                    self._cache_list_attractions[cache_key] = result
                    return result
            except Exception:
                pass
        if self._env:
            try:
                df = self._env.attractions.select(city, key="name", func=lambda x: True)
                records = _df_to_records(df.head(limit) if hasattr(df, "head") else df)
                result = [r for r in records if r.get("name")]
                self._cache_list_attractions[cache_key] = result
                return result
            except Exception:
                pass
        records = load_csv_records(city, "attraction", self.lang)
        if records:
            result = records[:limit]
        else:
            result = self._db.search_pois(city, filters={"category": "attraction"})[:limit]
        self._cache_list_attractions[cache_key] = result
        return result

    def list_restaurants(self, city: str, limit: int = 30) -> list[dict[str, Any]]:
        cache_key = f"{city}:{limit}"
        if cache_key in self._cache_list_restaurants:
            return self._cache_list_restaurants[cache_key]
        if self._agent_env:
            try:
                records = self._agent_env.select_restaurants(city, "name", "ne", "")
                if records:
                    result = records[:limit]
                    self._cache_list_restaurants[cache_key] = result
                    return result
            except Exception:
                pass
        if self._env:
            try:
                df = self._env.restaurants.select(city, key="name", func=lambda x: True)
                result = _df_to_records(df.head(limit) if hasattr(df, "head") else df)
                self._cache_list_restaurants[cache_key] = result
                return result
            except Exception:
                pass
        records = load_csv_records(city, "restaurant", self.lang)
        if records:
            result = records[:limit]
        else:
            result = self._db.search_pois(city, filters={"category": "restaurant"})[:limit]
        self._cache_list_restaurants[cache_key] = result
        return result

    def list_hotels(self, city: str, limit: int = 20) -> list[dict[str, Any]]:
        cache_key = f"{city}:{limit}"
        if cache_key in self._cache_list_hotels:
            return self._cache_list_hotels[cache_key]
        if self._agent_env:
            try:
                records = self._agent_env.select_accommodations(city, "name", "ne", "")
                if records:
                    result = records[:limit]
                    self._cache_list_hotels[cache_key] = result
                    return result
            except Exception:
                pass
        if self._env:
            try:
                df = self._env.accommodations.select(city, key="name", func=lambda x: True)
                result = _df_to_records(df.head(limit) if hasattr(df, "head") else df)
                self._cache_list_hotels[cache_key] = result
                return result
            except Exception:
                pass
        records = load_csv_records(city, "hotel", self.lang)
        if records:
            result = records[:limit]
        else:
            result = self._db.search_pois(city, filters={"category": "hotel"})[:limit]
        self._cache_list_hotels[cache_key] = result
        return result

    # ------------------------------------------------------------------
    # nearby 查询
    # ------------------------------------------------------------------

    def hotels_nearby(
        self,
        city: str,
        anchor: str,
        topk: int = 10,
        max_dist_km: float = 8.0,
    ) -> list[dict[str, Any]]:
        """按地标距离筛选酒店。"""
        if self._agent_env:
            try:
                records = self._agent_env.accommodations_nearby(city, anchor, topk, max_dist_km)
                if records:
                    return records[:topk]
            except Exception:
                pass
        if self._env:
            try:
                df = self._env.accommodations.nearby(city, anchor, topk=topk, dist=max_dist_km)
                return _df_to_records(df)
            except Exception:
                pass
        hotels = self.list_hotels(city, limit=100)
        return hotels[:topk]

    def attractions_nearby(
        self,
        city: str,
        point: str,
        topk: int = 10,
        max_dist_km: float = 5.0,
    ) -> list[dict[str, Any]]:
        if self._agent_env:
            try:
                records = self._agent_env.attractions_nearby(city, point, topk, max_dist_km)
                if records:
                    return records[:topk]
            except Exception:
                pass
        if self._env:
            try:
                df = self._env.attractions.nearby(city, point, topk=topk, dist=max_dist_km)
                return _df_to_records(df)
            except Exception:
                pass
        return self.list_attractions(city, limit=topk)

    def restaurants_nearby(
        self,
        city: str,
        point: str,
        topk: int = 10,
        max_dist_km: float = 5.0,
    ) -> list[dict[str, Any]]:
        """查找附近餐厅（新增，供 repair 使用）。"""
        if self._agent_env:
            try:
                records = self._agent_env.restaurants_nearby(city, point, topk, max_dist_km)
                if records:
                    return records[:topk]
            except Exception:
                pass
        if self._env:
            try:
                df = self._env.restaurants.nearby(city, point, topk=topk, dist=max_dist_km)
                return _df_to_records(df)
            except Exception:
                pass
        return self.list_restaurants(city, limit=topk)

    def poi_lat_lon(self, city: str, name: str) -> dict[str, Any] | None:
        """查询 POI 经纬度（供坐标 fallback）。"""
        if self._agent_env:
            try:
                return self._agent_env.poi_lat_lon(city, name)
            except Exception:
                pass
        return None

    # ------------------------------------------------------------------
    # 交通
    # ------------------------------------------------------------------

    def poi_distance(
        self,
        city: str,
        poi1: str,
        poi2: str,
        start_time: str = "09:00",
        mode: str = "walk",
    ) -> float | None:
        """两点距离（km）。请求级缓存，优先坐标 Haversine 估算。"""
        if poi1 == poi2 or not poi1 or not poi2:
            return 0.0
        cache_key = (city, poi1, poi2, start_time, mode)
        if cache_key in self._cache_distance:
            return self._cache_distance[cache_key]

        result: float | None = None
        # 1. 优先：坐标 Haversine（纯计算，不调后端）
        dist_km = _resolve_coord_distance(city, poi1, poi2)
        if dist_km is not None:
            result = dist_km
        # 2. fallback: agent_env
        elif self._agent_env:
            try:
                segments = self._agent_env.goto(city, poi1, poi2, start_time, mode)
                if segments:
                    result = float(segments[0].get("distance", 0))
            except Exception:
                pass
        if result is None and self._env:
            try:
                segments = self._env.transportation.goto(city, poi1, poi2, start_time, mode)
                if isinstance(segments, list) and segments:
                    result = float(segments[0].get("distance", 0))
            except Exception:
                pass
        self._cache_distance[cache_key] = result
        return result

    def select_intercity(
        self,
        start_city: str,
        end_city: str,
        mode: str = "airplane",
        earliest: str = "06:00",
    ) -> dict[str, Any] | None:
        """查询城际交通，失败时尝试换 mode 和时间，最终返回 None 绝不伪造数据。"""
        earliest_min = time_to_minutes(earliest)

        def _departs_after(row: dict, mode: str) -> bool:
            t = str(row.get("BeginTime") or row.get("start_time") or "00:00")
            return time_to_minutes(t) >= earliest_min

        # 尝试 agent_env
        if self._agent_env:
            for try_mode in (mode, "train" if mode == "airplane" else "airplane"):
                for try_time in (earliest, "06:00", "08:00", "10:00"):
                    try:
                        rows = self._agent_env.intercity_transport_select(
                            start_city, end_city, try_mode, try_time,
                        )
                        if rows:
                            # agent_env 可能忽略时间过滤，手动再次过滤
                            filtered = [r for r in rows if _departs_after(r, try_mode)]
                            if filtered:
                                return _normalize_intercity_row(filtered[0], try_mode)
                    except Exception:
                        pass

        # 尝试 direct WorldEnv
        if self._env:
            for try_mode in (mode, "train" if mode == "airplane" else "airplane"):
                for try_time in (earliest, "06:00", "08:00", "10:00"):
                    try:
                        df = self._env.intercitytransport.select(
                            start_city, end_city, try_mode, earliest_leave_time=try_time,
                        )
                        if df is not None and not getattr(df, "empty", True):
                            records = _df_to_records(df)
                            if records:
                                row = dict(records[0])
                                row["type"] = try_mode
                                return row
                    except Exception:
                        pass

        # CSV/JSON fallback: 加载真实数据（不伪造 ID）
        from src.data_layer.chinatravel_bridge import (
            CITY_NAMES_EN,
            CITY_NAMES_ZH,
            database_dir,
        )
        db = database_dir(self.lang)
        # 也可查中文 database（城市名是中文）
        from src.data_layer.chinatravel_bridge import database_dir as _db_dir_any
        db_zh = _db_dir_any("zh")

        for db_candidate in (db, db_zh):
            if db_candidate is None:
                continue
            for try_mode in (mode, "train" if mode == "airplane" else "airplane"):
                # 尝试中英文城市名
                for city_pair in (
                    (start_city, end_city),
                    (_eng_to_zh(start_city), _eng_to_zh(end_city)),
                ):
                    if city_pair[0] is None or city_pair[1] is None:
                        continue
                    sc, ec = city_pair
                    # JSON 文件（train）
                    json_name = f"from_{sc}_to_{ec}.json"
                    json_path = db_candidate / "intercity_transport" / "train" / json_name
                    if json_path.exists():
                        import json as _json
                        rows = _json.loads(json_path.read_text(encoding="utf-8"))
                        if isinstance(rows, list) and rows:
                            filtered = [r for r in rows if time_to_minutes(
                                str(r.get("BeginTime") or r.get("start_time") or "00:00")
                            ) >= time_to_minutes(earliest)]
                            if filtered:
                                row = dict(filtered[0])
                                row["type"] = "train"
                                # TrainID 必须来自真实数据
                                row["TrainID"] = str(row.get("TrainID", row.get("id", "")))
                                if not row["TrainID"]:
                                    continue  # 跳过无 ID 记录，不伪造
                                return row
                    # JSONL 文件（airplane）
                    jsonl_path = db_candidate / "intercity_transport" / "airplane.jsonl"
                    if jsonl_path.exists():
                        import json as _json
                        candidates = []
                        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
                            if not line.strip():
                                continue
                            try:
                                rec = _json.loads(line)
                            except Exception:
                                continue
                            if (str(rec.get("From") or rec.get("start") or "") == sc
                                    and str(rec.get("To") or rec.get("end") or "") == ec):
                                if time_to_minutes(
                                    str(rec.get("BeginTime") or rec.get("start_time") or "00:00")
                                ) >= time_to_minutes(earliest):
                                    candidates.append(rec)
                        if candidates:
                            row = dict(candidates[0])
                            row["type"] = "airplane"
                            if "FlightID" not in row:
                                row["FlightID"] = str(row.get("FlightID", row.get("id", "")))
                            return row

        # 所有后端都失败 — 不伪造数据
        return None

    def goto(
        self,
        city: str,
        start: str,
        end: str,
        start_time: str,
        mode: str = "metro",
        people: int = 1,
        taxi_cars: int | None = None,
    ) -> list[dict[str, Any]]:
        """市内交通，来自 WorldEnv/agent_env 真实数据。请求级缓存。

        P0: 真实后端优先。agent_env → direct WorldEnv → 坐标估算兜底。
        缓存 key 仅用 (city, start, end, mode)，忽略 start_time。
        """
        if not start or not end or start == end:
            return []
        cache_key = (city, start, end, start_time, mode)
        if cache_key in self._cache_goto:
            return annotate_transports(self._cache_goto[cache_key], people, taxi_cars)

        segments: list[dict[str, Any]] | None = None

        def _shape_ok(segs: list[dict[str, Any]], expected_mode: str) -> bool:
            if not isinstance(segs, list) or not segs:
                return False
            modes = [str(s.get("mode", "")) for s in segs]
            if any(not s.get("start") or not s.get("end") for s in segs):
                return False
            if any(not s.get("start_time") or not s.get("end_time") for s in segs):
                return False
            if expected_mode == "metro":
                return len(segs) == 3 and modes == ["walk", "metro", "walk"]
            if expected_mode in ("taxi", "walk"):
                return len(segs) == 1 and modes[0] == expected_mode
            return False

        # 1. agent_env (real data)
        if self._agent_env:
            try:
                segs = self._agent_env.goto(city, start, end, start_time, mode)
                if _shape_ok(segs, mode):
                    segments = segs
            except Exception:
                pass

        # 2. direct WorldEnv (real data)
        if segments is None and self._env:
            try:
                segs = self._env.transportation.goto(city, start, end, start_time, mode)
                if _shape_ok(segs, mode):
                    segments = segs
            except Exception:
                pass

        # 3. fallback: metro→taxi→walk via agent_env
        # 4. ultimate fallback: coordinate estimation (last resort)
        if segments is None:
            if mode == "metro":
                self._cache_goto[cache_key] = []
                return []
            dist_km = _resolve_coord_distance(city, start, end)
            if dist_km is not None:
                speed_kmh = 30.0 if mode == "taxi" else 5.0
                dur_min = max(5, int(dist_km / speed_kmh * 60))
                end_time_str = add_minutes(start_time, dur_min)
                segments = [{
                    "start": start, "end": end, "mode": mode,
                    "start_time": start_time, "end_time": end_time_str,
                    "cost": 0.0, "price": 0.0, "distance": round(dist_km, 2),
                }]
            else:
                # absolute last resort
                end_time_str = add_minutes(start_time, 20)
                segments = [{
                    "start": start, "end": end, "mode": mode,
                    "start_time": start_time, "end_time": end_time_str,
                    "cost": 0.0, "price": 0.0, "distance": 1.5,
                }]

        self._cache_goto[cache_key] = segments
        return annotate_transports(segments, people, taxi_cars)

    def is_attraction_open(self, city: str, poi_name: str, time_str: str) -> bool:
        cache_key = (city, poi_name, time_str)
        if cache_key in self._cache_attraction_open:
            return self._cache_attraction_open[cache_key]

        result: bool = True  # fallback: assume open
        # try agent_env by name → get id → is_open
        if self._agent_env:
            try:
                records = self._agent_env.select_attractions(city, "name", "eq", poi_name)
                if records:
                    poi_id = records[0].get("id")
                    if poi_id is not None:
                        result = self._agent_env.is_attraction_open(city, int(poi_id), time_str)
                        self._cache_attraction_open[cache_key] = result
                        return result
            except Exception:
                pass
        if self._env:
            try:
                df = self._env.attractions.select(city, key="name", func=lambda x: x == poi_name)
                records = _df_to_records(df)
                if records:
                    poi_id = int(records[0].get("id", 0))
                    result = bool(self._env.attractions.id_is_open(city, poi_id, time_str))
                    self._cache_attraction_open[cache_key] = result
                    return result
            except Exception:
                pass
        # CSV fallback: 查数据库 opentime/endtime
        try:
            records = self.list_attractions(city, limit=5000)
            for r in records:
                r_name = r.get("name", "")
                if r_name == poi_name or poi_name in r_name or r_name in poi_name:
                    opentime = str(r.get("opentime", "00:00"))
                    endtime = str(r.get("endtime", "24:00"))
                    cur_min = time_to_minutes(time_str)
                    open_min = time_to_minutes(opentime)
                    close_min = time_to_minutes(endtime)
                    if close_min <= open_min:
                        close_min += 24 * 60
                        if cur_min < open_min:
                            cur_min += 24 * 60
                    result = open_min <= cur_min < close_min
                    break
        except Exception:
            pass
        self._cache_attraction_open[cache_key] = result
        return result

    def is_restaurant_open(self, city: str, name: str, time_str: str) -> bool:
        cache_key = (city, name, time_str)
        if cache_key in self._cache_restaurant_open:
            return self._cache_restaurant_open[cache_key]

        result: bool = True  # fallback: assume open
        if self._agent_env:
            try:
                records = self._agent_env.select_restaurants(city, "name", "eq", name)
                if records:
                    poi_id = records[0].get("id")
                    if poi_id is not None:
                        result = self._agent_env.is_restaurant_open(city, int(poi_id), time_str)
                        self._cache_restaurant_open[cache_key] = result
                        return result
            except Exception:
                pass
        if self._env:
            try:
                df = self._env.restaurants.select(city, key="name", func=lambda x: x == name)
                records = _df_to_records(df)
                if records:
                    poi_id = int(records[0].get("id", 0))
                    result = bool(self._env.restaurants.id_is_open(city, poi_id, time_str))
                    self._cache_restaurant_open[cache_key] = result
                    return result
            except Exception:
                pass
        # CSV fallback: 查数据库 opentime/endtime
        try:
            records = self.list_restaurants(city, limit=5000)
            for r in records:
                r_name = r.get("name", "")
                if r_name == name or name in r_name or r_name in name:
                    opentime = str(r.get("opentime", "00:00"))
                    endtime = str(r.get("endtime", "24:00"))
                    cur_min = time_to_minutes(time_str)
                    open_min = time_to_minutes(opentime)
                    close_min = time_to_minutes(endtime)
                    if close_min <= open_min:
                        close_min += 24 * 60
                        if cur_min < open_min:
                            cur_min += 24 * 60
                    result = open_min <= cur_min < close_min
                    break
        except Exception:
            pass
        self._cache_restaurant_open[cache_key] = result
        return result

    def candidates_from_records(
        self,
        records: list[dict[str, Any]],
    ) -> list[POICandidate]:
        return [_record_to_candidate(r) for r in records if r.get("name")]


_client: SandboxClient | None = None


def _resolve_coord_distance(city: str, poi_a: str, poi_b: str) -> float | None:
    """解析两个 POI 名对应坐标的 Haversine 距离（km）。

    若任一 POI 无坐标则返回 None，由调用方回退 agent_env。
    优先使用已有缓存（不管 limit），避免重复查询后端。
    """
    import math

    # 本地坐标缓存：避免每次在 list 中扫描同名 POI
    _coord_lookup: dict[str, tuple[float, float] | None] = {}

    def _get_coords(name: str) -> tuple[float, float] | None:
        if not name:
            return None
        if name in _coord_lookup:
            return _coord_lookup[name]
        s = _client
        if s is None:
            _coord_lookup[name] = None
            return None
        # 1. 优先从已有 list_* 缓存中查找（不调后端）
        for cache_dict in (s._cache_list_attractions, s._cache_list_restaurants, s._cache_list_hotels):
            # 遍历所有已缓存的 limit=* keys
            for key, records in list(cache_dict.items()):
                if not key.startswith(city + ":"):
                    continue
                for r in records:
                    r_name = str(r.get("name", ""))
                    if r_name == name or name in r_name or r_name in name:
                        lat = r.get("lat") or r.get("latitude")
                        lon = r.get("lon") or r.get("lng") or r.get("longitude")
                        if lat is not None and lon is not None:
                            try:
                                result = (float(lat), float(lon))
                                _coord_lookup[name] = result
                                return result
                            except (TypeError, ValueError):
                                _coord_lookup[name] = None
                                return None
        # 2. 缓存中没有：调一次 list_* 获取完整数据（limit=5000，后续会缓存）
        for getter in (s.list_attractions, s.list_restaurants, s.list_hotels):
            try:
                records = getter(city, limit=5000)
            except Exception:
                continue
            for r in records:
                r_name = str(r.get("name", ""))
                if r_name == name or name in r_name or r_name in name:
                    lat = r.get("lat") or r.get("latitude")
                    lon = r.get("lon") or r.get("lng") or r.get("longitude")
                    if lat is not None and lon is not None:
                        try:
                            result = (float(lat), float(lon))
                            _coord_lookup[name] = result
                            return result
                        except (TypeError, ValueError):
                            _coord_lookup[name] = None
                            return None
        _coord_lookup[name] = None
        return None

    ca = _get_coords(poi_a)
    cb = _get_coords(poi_b)
    if ca is None or cb is None:
        return None

    r = 6371.0
    phi1, phi2 = math.radians(ca[0]), math.radians(cb[0])
    dphi = math.radians(cb[0] - ca[0])
    dlambda = math.radians(cb[1] - ca[1])
    x = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(x))


def get_sandbox(lang: str | None = None) -> SandboxClient:
    global _client
    resolved = lang or "en"
    if _client is None or _client.lang != resolved:
        _client = SandboxClient(lang=resolved)
    return _client


def get_chinatravel_status() -> dict[str, Any]:
    """诊断 ChinaTravel 接入状态。"""
    root = resolve_chinatravel_root()
    config = load_project_config()
    we_config = config.get("world_env", {}) if config else {}
    backend_name = we_config.get("backend", "auto")

    agent_env_ok = False
    try:
        be = AgentEnvBackend(agent_env_cwd=we_config.get("agent_env_cwd", "ChinaTravel"))
        agent_env_ok = be.available
    except Exception:
        pass

    return {
        "root": str(root) if root else None,
        "database_ready": is_chinatravel_database_ready("en"),
        "world_env": get_world_env("en") is not None,
        "agent_env": agent_env_ok,
        "backend_configured": backend_name,
        "backend_resolved": _resolve_backend(backend_name, we_config.get("agent_env_cwd", "ChinaTravel")),
    }
