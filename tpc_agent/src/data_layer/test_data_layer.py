"""data_layer 模块独立测试。

运行方式（在 tpc_agent 目录下）::

    python src/data_layer/test_data_layer.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

# 确保可从 tpc_agent 根目录导入 src 包
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data_layer.database import TravelDatabase, get_poi_by_id, search_pois
from src.data_layer.loaders import load_queries_batch, load_query, query_from_dict
from src.data_layer.paths import get_project_root, resolve_data_path


def _ok(name: str) -> None:
    print(f"  [PASS] {name}")


def _fail(name: str, msg: str) -> None:
    print(f"  [FAIL] {name}: {msg}")
    raise AssertionError(msg)


def test_paths() -> None:
    """测试路径解析。"""
    root = get_project_root()
    assert (root / "main.py").exists(), "项目根目录应包含 main.py"
    raw_path = resolve_data_path("data_raw", "data/raw")
    assert raw_path.is_absolute(), "data 路径应解析为绝对路径"
    _ok("paths")


def test_load_real_training_query() -> None:
    """使用本地 training data 测试 query 加载。"""
    training_dir = get_project_root() / "data" / "training data"
    if not training_dir.exists():
        print("  [SKIP] 未找到 data/training data，跳过真实数据测试")
        return

    files = sorted(training_dir.glob("*.json"))
    assert files, "training data 目录应有 json 文件"

    query = load_query(files[0])
    assert query.query_id, "query_id 不能为空"
    assert query.raw_text, "raw_text 应从 nature_language 提取"
    assert query.metadata.get("target_city"), "metadata 应保留 target_city"
    assert query.metadata.get("hard_logic_py"), "metadata 应保留 hard_logic_py"
    _ok(f"load_query -> id={query.query_id}, city={query.metadata.get('target_city')}")

    batch = load_queries_batch(training_dir)
    assert len(batch) >= 1
    _ok(f"load_queries_batch -> {len(batch)} 条")


def test_query_from_dict_generic() -> None:
    """测试通用 dict 格式。"""
    data = {
        "query_id": "test_001",
        "raw_text": "去成都玩3天，预算3000",
        "start_city": "上海",
        "target_city": "成都",
        "days": 3,
    }
    query = query_from_dict(data)
    assert query.query_id == "test_001"
    assert "成都" in query.raw_text
    _ok("query_from_dict")


def test_database_with_temp_sandbox() -> None:
    """使用临时沙盒数据测试 POI 检索与交通矩阵。"""
    with tempfile.TemporaryDirectory() as tmp:
        sandbox = Path(tmp)
        city = "成都"
        attractions_dir = sandbox / "attractions"
        attractions_dir.mkdir(parents=True)

        pois = [
            {
                "id": "poi_001",
                "name": "宽窄巷子",
                "latitude": 30.663,
                "longitude": 104.052,
                "price": 0,
            },
            {
                "id": "poi_002",
                "name": "武侯祠",
                "latitude": 30.647,
                "longitude": 104.046,
                "price": 50,
            },
        ]
        with open(attractions_dir / f"{city}.json", "w", encoding="utf-8") as f:
            json.dump(pois, f, ensure_ascii=False)

        db = TravelDatabase(sandbox_root=sandbox)

        # 按 ID 查询
        poi = db.get_poi_by_id("poi_001", city=city)
        assert poi.get("name") == "宽窄巷子", f"期望宽窄巷子，得到 {poi}"
        _ok("get_poi_by_id")

        # 按城市搜索
        results = db.search_pois(city, filters={"category": "attraction", "max_price": 10})
        assert len(results) == 1 and results[0]["id"] == "poi_001"
        _ok("search_pois")

        # 交通矩阵
        matrix = db.get_transport_matrix(["poi_001", "poi_002"], city=city)
        assert matrix["poi_ids"] == ["poi_001", "poi_002"]
        assert matrix["distance_km"][0][1] > 0
        assert matrix["duration_min"][0][1] > 0
        _ok("get_transport_matrix")


def test_module_level_api() -> None:
    """测试模块级快捷函数可调用（无 sandbox 时返回空结果不报错）。"""
    _ = get_poi_by_id("not_exist_id", city="不存在城市")
    _ = search_pois("不存在城市")
    _ok("module_level_api")


def main() -> None:
    print("=" * 50)
    print("data_layer 测试")
    print("=" * 50)

    test_paths()
    test_query_from_dict_generic()
    test_load_real_training_query()
    test_database_with_temp_sandbox()
    test_module_level_api()

    print("=" * 50)
    print("全部 data_layer 测试通过")
    print("=" * 50)


if __name__ == "__main__":
    main()
