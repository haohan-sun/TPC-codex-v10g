"""Official eval smoke runner — 用 ChinaTravel 官方 split 生成结果并检查 schema。

用法::

    python scripts/run_official_eval_smoke.py --split easy --limit 10 --method TPCAgent_TPCLLM --timeout 300 --resume
    python scripts/run_official_eval_smoke.py --split demo1_training_single --method TPCAgent_TPCLLM

功能：
    1. 选择官方 split（easy/medium/human/demo1_training_single 等），limit 可配置。
    2. 从 ChinaTravel/chinatravel/data/ 或 en/ 子目录加载 query。
    3. 调用 TPCAgent.run 生成 plan。
    4. 写入 ChinaTravel/results/{method}/{uid}.json，供 eval_tpc.py 直接读取。
    5. 支持 --resume（跳过已有结果）。
    6. 输出生成数、schema pass 数。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

# Windows GBK 兼容：强制 stdout 使用 UTF-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from func_timeout import func_timeout, FunctionTimedOut
except ImportError:
    FunctionTimedOut = TimeoutError

    def func_timeout(timeout, func, args=None, kwargs=None):
        return func(*(args or ()), **(kwargs or {}))


# ── config helpers ──────────────────────────────────────────────────────────

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
    config = _load_config()
    raw = (config.get("paths") or {}).get("chinatravel_root")
    if raw:
        p = Path(raw)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        if p.exists():
            return p
    candidate = PROJECT_ROOT / "ChinaTravel"
    return candidate if candidate.exists() else None


# ── query loading ───────────────────────────────────────────────────────────

def load_official_split(
    split: str,
    limit: int = 0,
    ct_root: Path | None = None,
    lang: str = "en",
) -> tuple[list[str], dict[str, dict]]:
    """加载官方 split 的 uid 列表及 query 数据。

    优先使用 ChinaTravel 官方 load_query（支持 HuggingFace 下载），
    回退到本地文件搜索。

    Returns:
        (uids, {uid: query_dict})
    """
    if ct_root is None:
        ct_root = _resolve_chinatravel_root()
    if ct_root is None:
        print("ERROR: 找不到 ChinaTravel 目录。")
        return [], {}

    # 尝试官方 load_query（含 HuggingFace datasets fallback）
    try:
        ct_str = str(ct_root)
        if ct_str not in sys.path:
            sys.path.insert(0, ct_str)
        from chinatravel.data.load_datasets import load_query

        # 构造虚拟 args（使用 SimpleNamespace 避免 class body scope 问题）
        # oracle_translation 默认 True 以保留 hard_logic_py，与本地 split 行为一致
        fake_args = SimpleNamespace(
            splits=split,
            lang=lang,
            oracle_translation=True,
        )
        uids, query_data = load_query(fake_args)
        if uids:
            query_ids = uids
            if limit > 0:
                query_ids = uids[:limit]
                query_data = {k: v for k, v in query_data.items() if k in query_ids}
            print(f"加载 split={split}, {len(query_ids)} uids (via chinatravel load_query)")
            return query_ids, query_data
    except Exception as exc:
        print(f"官方 load_query 失败: {exc}, 回退到本地搜索...")

    # 回退：本地文件搜索
    split_file = (
        ct_root / "chinatravel" / "evaluation" / "default_splits" / f"{split}.txt"
    )
    if not split_file.exists():
        print(f"ERROR: split 文件不存在: {split_file}")
        return [], {}

    uids = [
        line.strip()
        for line in split_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if limit > 0:
        uids = uids[:limit]

    print(f"加载 split={split}, {len(uids)} uids (本地)")

    query_data: dict[str, dict] = {}
    for data_sub in ("chinatravel/data/en", "chinatravel/data"):
        data_root = ct_root / data_sub
        if not data_root.exists():
            continue
        for uid in uids:
            if uid in query_data:
                continue
            for json_path in data_root.rglob(f"{uid}.json"):
                query_data[uid] = json.loads(json_path.read_text(encoding="utf-8"))
                break

    print(f"  找到 {len(query_data)} 条 query 数据")
    missing = set(uids) - set(query_data.keys())
    if missing:
        print(f"  WARNING: {len(missing)} 条 query 数据缺失")

    return uids, query_data


# ── schema check ────────────────────────────────────────────────────────────

def _check_schema(plan: dict) -> list[str]:
    """快速 schema 检查（不依赖 OfficialPlan wrapper）。"""
    import re
    time_re = re.compile(r"^\d{2}:\d{2}$")
    issues: list[str] = []

    for field in ("people_number", "start_city", "target_city", "itinerary"):
        if field not in plan:
            issues.append(f"missing top: {field}")

    for day in plan.get("itinerary", []):
        for act in day.get("activities", []):
            for tf in ("start_time", "end_time"):
                t = act.get(tf, "")
                if t and not time_re.match(str(t)):
                    issues.append(
                        f"day{day.get('day')} {act.get('type')} {tf}={t!r}"
                    )
            for seg in act.get("transports", []):
                for tf in ("start_time", "end_time"):
                    t = seg.get(tf, "")
                    if t and not time_re.match(str(t)):
                        issues.append(
                            f"day{day.get('day')} transport {tf}={t!r}"
                        )
    return issues


# ── main ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Official eval smoke runner")
    parser.add_argument("--split", type=str, default="easy", help="官方 split 名")
    parser.add_argument("--limit", type=int, default=10, help="最多处理条数")
    parser.add_argument("--method", "-m", type=str, default="TPCAgent_TPCLLM")
    parser.add_argument("--timeout", "-t", type=int, default=300)
    parser.add_argument("--resume", action="store_true", help="跳过已有结果")
    parser.add_argument("--lang", choices=["zh", "en"], default="en")
    args = parser.parse_args()

    ct_root = _resolve_chinatravel_root()
    if ct_root is None:
        print("FATAL: ChinaTravel 目录不可用。")
        sys.exit(1)

    # 对齐官方 eval_tpc.py: --lang en 时方法名自动加 _en 后缀
    effective_method = args.method
    if args.lang == "en" and not args.method.endswith("_en"):
        effective_method = args.method + "_en"

    results_dir = ct_root / "results" / effective_method
    results_dir.mkdir(parents=True, exist_ok=True)

    # 加载 split
    uids, query_data = load_official_split(args.split, args.limit, ct_root, lang=args.lang)
    if not uids:
        print("无 query 可处理。")
        return

    # 检查 hard_logic_py 可用性
    has_hard_logic = False
    for q in query_data.values():
        if q.get("hard_logic_py"):
            has_hard_logic = True
            break
    if not has_hard_logic:
        print(
            "\n⚠️  注意: 当前 split 的 query 不含 hard_logic_py 字段。\n"
            "   官方 hard constraints (C-LPR/FPR/Overall) 将无法计算。\n"
            "   若需完整评分，请使用带 hard_logic_py 的本地 split。\n"
        )

    # 导入 agent
    from tpc_agent import TPCAgent
    from tpc_llm import TPCLLM

    agent = TPCAgent(
        env=None,
        backbone_llm=TPCLLM(),
        log_dir=str(results_dir),
        cache_dir=str(results_dir),
        lang=args.lang,
    )

    succ_count, schema_ok, total = 0, 0, 0

    for i, uid in enumerate(uids):
        print(f"[{i + 1}/{len(uids)}] {uid}", end=" ")

        out_path = results_dir / f"{uid}.json"
        if args.resume and out_path.exists():
            print("→ skip (exists)")
            continue

        query = query_data.get(uid)
        if query is None:
            print("→ SKIP (no query data)")
            continue

        total += 1

        try:
            succ, plan = func_timeout(
                args.timeout,
                agent.run,
                args=(query,),
                kwargs={"prob_idx": uid, "oralce_translation": False},
            )
        except FunctionTimedOut:
            succ, plan = False, {
                "people_number": query.get("people_number", 1),
                "start_city": query.get("start_city", ""),
                "target_city": query.get("target_city", ""),
                "itinerary": [],
                "error": f"timeout after {args.timeout}s",
            }
        except Exception as exc:
            succ, plan = False, {
                "people_number": query.get("people_number", 1),
                "start_city": query.get("start_city", ""),
                "target_city": query.get("target_city", ""),
                "itinerary": [],
                "error": f"{type(exc).__name__}: {exc}",
            }

        if succ:
            succ_count += 1

        issues = _check_schema(plan)
        if not issues:
            schema_ok += 1

        # 写结果
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

        tag = "OK" if not issues else f"schema issues: {issues[:3]}"
        print(f"→ succ={succ} {tag}")

    print("=" * 50)
    print(f"生成: {total}, 成功: {succ_count}, schema pass: {schema_ok}/{total}")

    if total == 0:
        print("无结果文件生成。")
        return

    # 提示 eval 命令
    eval_cmd = f"cd {ct_root} && python eval_tpc.py --splits {args.split} --method {args.method} --lang {args.lang}"
    print(f"\n官方 eval 命令:\n  {eval_cmd}")
    if effective_method != args.method:
        print(f"  实际读取目录: ChinaTravel/results/{effective_method}/")

    if not has_hard_logic:
        print(
            "\n⚠️  当前 split 缺 hard_logic_py，官方 C-LPR/FPR/Overall 将被跳过。\n"
            "   使用 demo1_training_single split 可验证完整评分流程。"
        )


if __name__ == "__main__":
    main()
