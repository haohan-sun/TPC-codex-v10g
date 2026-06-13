"""本地批量运行脚本，接口对齐 ChinaTravel run_tpc.py。

用法::

    python run_tpc.py --splits training --agent TPCAgent --llm TPCLLM
    python run_tpc.py --splits training --index 20250324234255286741
    python run_tpc.py --splits easy --official-results --limit 10

结果写入（默认）: data/outputs/results/TPCAgent_TPCLLM/{uid}.json
结果写入（--official-results）: ChinaTravel/results/TPCAgent_TPCLLM/{uid}.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Windows GBK 兼容
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 项目根目录加入 path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from func_timeout import func_timeout, FunctionTimedOut
except ImportError:
    FunctionTimedOut = TimeoutError

    def func_timeout(timeout, func, args=None, kwargs=None):
        return func(*(args or ()), **(kwargs or {}))


from tpc_agent import TPCAgent
from tpc_llm import TPCLLM


def _load_config() -> dict:
    config_path = PROJECT_ROOT / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        import yaml
        with open(config_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        return {}


def _resolve_chinatravel_root() -> Path | None:
    """按 config.yaml → PROJECT_ROOT 优先级解析 ChinaTravel 路径。"""
    config = _load_config()
    raw = (config.get("paths") or {}).get("chinatravel_root")
    if raw:
        p = Path(raw)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        if p.exists():
            return p
    # 回退：PROJECT_ROOT / ChinaTravel
    candidate = PROJECT_ROOT / "ChinaTravel"
    if candidate.exists():
        return candidate
    return None


def _load_official_query(uid: str, ct_root: Path) -> dict | None:
    """从 ChinaTravel data 目录加载单条 query（支持 en/ 子目录）。"""
    for data_sub in ("chinatravel/data/en", "chinatravel/data"):
        data_root = ct_root / data_sub
        if not data_root.exists():
            continue
        for sub in data_root.iterdir():
            if not sub.is_dir():
                continue
            candidate = sub / f"{uid}.json"
            if candidate.exists():
                with open(candidate, encoding="utf-8") as f:
                    return json.load(f)
    return None


def load_split_queries(
    splits: str,
    single_uid: str | None = None,
    *,
    limit: int = 0,
    official: bool = False,
) -> tuple[list[str], dict[str, dict]]:
    """加载 split 对应的 query 列表。

    查找顺序：
        1. data/splits/{splits}.txt
        2. data/training data/ （splits=training 时扫描）
        3. ChinaTravel 官方 split: chinatravel/evaluation/default_splits/{splits}.txt
           + chinatravel/data/ 或 chinatravel/data/en/
    """
    query_data: dict[str, dict] = {}
    query_ids: list[str] = []
    training_dir = PROJECT_ROOT / "data" / "training data"
    ct_root = _resolve_chinatravel_root()

    # 单条 uid 模式
    if single_uid:
        query_ids = [single_uid]
        # 先找本地 training data
        path = training_dir / f"{single_uid}.json"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                query_data[single_uid] = json.load(f)
            return query_ids, query_data
        # 再找 ChinaTravel official data
        if ct_root:
            q = _load_official_query(single_uid, ct_root)
            if q:
                query_data[single_uid] = q
                return query_ids, query_data
        return query_ids, query_data

    # split 模式：先尝试本地
    split_file = PROJECT_ROOT / "data" / "splits" / f"{splits}.txt"
    if split_file.exists():
        with open(split_file, encoding="utf-8") as f:
            query_ids = [line.strip() for line in f if line.strip()]

    # splits=training 且无 split 文件：扫描 training data 目录
    if not query_ids and splits == "training" and training_dir.exists():
        query_ids = sorted(p.stem for p in training_dir.glob("*.json"))

    # 仍未找到：尝试 ChinaTravel 官方 split
    if not query_ids and ct_root:
        ct_split = (
            ct_root / "chinatravel" / "evaluation" / "default_splits" / f"{splits}.txt"
        )
        if ct_split.exists():
            with open(ct_split, encoding="utf-8") as f:
                query_ids = [line.strip() for line in f if line.strip()]
            # 加载 query 内容
            for uid in query_ids:
                q = _load_official_query(uid, ct_root)
                if q:
                    query_data[uid] = q
            if query_data:
                if limit > 0:
                    query_ids = query_ids[:limit]
                    query_data = {k: v for k, v in query_data.items() if k in query_ids}
                return query_ids, query_data

    if limit > 0:
        query_ids = query_ids[:limit]

    # 从本地 training data 加载
    for uid in query_ids:
        if uid not in query_data:
            path = training_dir / f"{uid}.json"
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    query_data[uid] = json.load(f)

    return query_ids, query_data


def save_json(data: dict, path: Path) -> None:
    """保存 JSON 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="TPC Agent 批量运行（对齐官方 run_tpc.py）")
    parser.add_argument("--splits", "-s", type=str, default="training", help="split 名称")
    parser.add_argument("--index", "-id", type=str, default=None, help="只跑指定 uid")
    parser.add_argument("--limit", type=int, default=0, help="限制 query 数量（0=全部）")
    parser.add_argument("--skip", "-sk", type=int, default=0, help="1=跳过已有结果")
    parser.add_argument("--agent", "-a", type=str, default="TPCAgent")
    parser.add_argument("--llm", "-l", type=str, default="TPCLLM")
    parser.add_argument("--timeout", "-t", type=int, default=300, help="单条 query 超时秒数")
    parser.add_argument("--lang", choices=["zh", "en"], default="zh")
    parser.add_argument("--oracle_translation", action="store_true", help="本地 debug：保留 hard_logic_py")
    parser.add_argument(
        "--official-results", action="store_true",
        help="结果写入 ChinaTravel/results/{method}/ 供官方 eval_tpc.py 直接读取",
    )
    parser.add_argument("--resume", action="store_true", help="跳过已有结果文件")
    args = parser.parse_args()

    config = _load_config()
    timeout = args.timeout or config.get("adapter", {}).get("timeout_sec", 300)

    query_ids, query_data = load_split_queries(
        args.splits, single_uid=args.index,
        limit=args.limit, official=args.official_results,
    )
    if args.index:
        query_ids = [args.index]
        if args.index not in query_data:
            ids, data = load_split_queries(args.splits, single_uid=args.index)
            query_data.update(data)

    print(f"加载 {len(query_ids)} 条 query (split={args.splits})")

    method = f"{args.agent}_{args.llm}"
    if args.oracle_translation:
        method += "_oracletranslation"

    # 输出目录：--official-results → ChinaTravel/results/；否则 config → 默认
    ct_root = _resolve_chinatravel_root()
    if args.official_results and ct_root:
        results_dir = ct_root / "results" / method
    elif args.official_results and not ct_root:
        print("ERROR: --official-results 需要 ChinaTravel 目录可访问（检查 config.yaml paths.chinatravel_root）")
        sys.exit(1)
    else:
        adapter_cfg = config.get("adapter", {}) if config else {}
        results_rel = adapter_cfg.get("results_dir", "data/outputs/results")
        results_dir = (
            (PROJECT_ROOT / results_rel / method)
            if not Path(results_rel).is_absolute()
            else (Path(results_rel) / method)
        )

    cache_rel = (config.get("adapter", {}) or {}).get("cache_dir", "data/outputs/cache") if config else "data/outputs/cache"
    log_dir = (PROJECT_ROOT / cache_rel / method) if not Path(cache_rel).is_absolute() else (Path(cache_rel) / method)
    results_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    print(f"results_dir: {results_dir}")
    print(f"log_dir:     {log_dir}")

    agent = TPCAgent(
        env=None,
        backbone_llm=TPCLLM(),
        log_dir=str(log_dir),
        cache_dir=str(log_dir),
        lang=args.lang,
    )

    succ_count, schema_ok, eval_count = 0, 0, 0

    for i, uid in enumerate(query_ids):
        print("-" * 40)
        print(f"Process [{i + 1}/{len(query_ids)}], Success [{succ_count}/{eval_count}]")
        print(f"uid: {uid}")

        out_path = results_dir / f"{uid}.json"
        skip = args.skip or args.resume
        if skip and out_path.exists():
            print("skip (exists)")
            continue

        if uid not in query_data:
            print(f"WARNING: query 数据缺失，跳过 {uid}")
            continue

        eval_count += 1
        query_i = query_data[uid]

        try:
            succ, plan = func_timeout(
                timeout,
                agent.run,
                args=(query_i,),
                kwargs={"prob_idx": uid, "oralce_translation": args.oracle_translation},
            )
        except FunctionTimedOut:
            succ, plan = False, {
                "people_number": query_i.get("people_number", 1),
                "start_city": query_i.get("start_city", ""),
                "target_city": query_i.get("target_city", ""),
                "itinerary": [],
                "error": f"timeout after {timeout}s",
            }
        except Exception as exc:
            succ, plan = False, {
                "people_number": query_i.get("people_number", 1),
                "start_city": query_i.get("start_city", ""),
                "target_city": query_i.get("target_city", ""),
                "itinerary": [],
                "error": str(exc),
            }

        if succ:
            succ_count += 1

        # 简易 schema 检查（三位数时间等）
        from src.submission.format_checker import check_format
        plan_wrapper = type("OfficialPlan", (), {"itinerary": plan})()
        fmt_issues = check_format(plan_wrapper)
        if not fmt_issues:
            schema_ok += 1

        save_json(plan, out_path)
        status = "schema OK" if not fmt_issues else f"schema ISSUES: {fmt_issues[:3]}"
        print(f"succ={succ}, {status}, saved -> {out_path}")

    print("=" * 40)
    print(f"完成: {succ_count}/{eval_count} 成功, schema pass: {schema_ok}/{eval_count}")

    # 若写入 ChinaTravel/results/，提示可直接跑 eval
    if args.official_results and ct_root:
        eval_cmd = f"cd {ct_root} && python eval_tpc.py --splits {args.splits} --method {method} --lang {args.lang}"
        print(f"\n官方 eval 就绪，运行:\n  {eval_cmd}")


if __name__ == "__main__":
    main()
