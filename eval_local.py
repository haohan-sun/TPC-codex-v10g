"""本地 eval_tpc 对接脚本。

用法::

    python eval_local.py --splits training --method TPCAgent_TPCLLM

若已 clone ChinaTravel 并配置 paths.chinatravel_root，将调用官方 eval_tpc.py；
否则执行本地 schema 批量检查。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.verifier.eval_bridge import evaluate_plan_local, is_chinatravel_available, run_eval_tpc_batch


def _load_results(method: str) -> tuple[list[str], dict[str, dict]]:
    results_dir = PROJECT_ROOT / "data" / "outputs" / "results" / method
    if not results_dir.exists():
        print(f"结果目录不存在: {results_dir}")
        return [], {}

    plans: dict[str, dict] = {}
    uids = sorted(p.stem for p in results_dir.glob("*.json"))
    for uid in uids:
        with open(results_dir / f"{uid}.json", encoding="utf-8") as f:
            plans[uid] = json.load(f)
    return uids, plans


def run_local_eval(method: str) -> None:
    """无 ChinaTravel 时的本地 schema 批量评估。"""
    uids, plans = _load_results(method)
    if not uids:
        return

    scores = []
    for uid in uids:
        r = evaluate_plan_local(plans[uid], query_id=uid)
        scores.append(r["score"])
        status = "OK" if not r["errors"] else f"errors={len(r['errors'])}"
        print(f"  {uid}: score={r['score']:.1f} {status}")

    print(f"平均 score: {sum(scores) / len(scores):.2f} / {len(uids)} 条")


def main() -> None:
    parser = argparse.ArgumentParser(description="本地 eval 对接")
    parser.add_argument("--splits", "-s", default="training")
    parser.add_argument("--method", "-m", default="TPCAgent_TPCLLM")
    args = parser.parse_args()

    print(f"ChinaTravel 可用: {is_chinatravel_available()}")

    if is_chinatravel_available():
        print("调用官方 eval_tpc.py ...")
        result = run_eval_tpc_batch(args.splits, args.method)
        print(result.get("stdout", ""))
        if result.get("stderr"):
            print(result["stderr"], file=sys.stderr)
    else:
        print("使用本地 schema 评估 ...")
        run_local_eval(args.method)


if __name__ == "__main__":
    main()
