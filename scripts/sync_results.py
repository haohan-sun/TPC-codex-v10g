"""结果同步与 pre-eval 数量检查（P0.1 修复配套）。

用法::

    # 检查 results 数量与 split 是否对齐
    python scripts/sync_results.py --check --splits easy --method TPCAgent_TPCLLM --lang en

    # 将 {method} 的结果同步到 {method}_en（已有文件不覆盖）
    python scripts/sync_results.py --sync --method TPCAgent_TPCLLM --lang en

    # 干跑：只显示将复制哪些文件
    python scripts/sync_results.py --sync --dry-run --method TPCAgent_TPCLLM --lang en
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_split_ids(splits: str) -> list[str]:
    """加载 split 中的 query ID 列表。"""
    local = PROJECT_ROOT / "data" / "splits" / f"{splits}.txt"
    if local.exists():
        with open(local, encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]

    ct = PROJECT_ROOT / "ChinaTravel" / "chinatravel" / "evaluation" / "default_splits" / f"{splits}.txt"
    if ct.exists():
        with open(ct, encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]

    training = PROJECT_ROOT / "data" / "training data"
    if splits == "training" and training.exists():
        return sorted(p.stem for p in training.glob("*.json"))

    return []


def load_result_ids(results_dir: Path) -> list[str]:
    """加载已有结果文件的 query ID 列表。"""
    if not results_dir.exists():
        return []
    return sorted(p.stem for p in results_dir.glob("*.json"))


def check_counts(splits: str, method: str, lang: str) -> dict:
    """检查 results 数量与 split query 数量是否对齐。"""
    if lang == "en" and not method.endswith("_en"):
        eval_method = method + "_en"
    else:
        eval_method = method

    ct_root = PROJECT_ROOT / "ChinaTravel"
    results_dir = ct_root / "results" / eval_method

    split_ids = load_split_ids(splits)
    result_ids = load_result_ids(results_dir)

    missing = sorted(set(split_ids) - set(result_ids))
    extra = sorted(set(result_ids) - set(split_ids))
    available = len(split_ids) - len(missing)

    report = {
        "splits": splits,
        "method": eval_method,
        "lang": lang,
        "split_count": len(split_ids),
        "available_count": available,
        "result_count": len(result_ids),
        "results_dir": str(results_dir),
        "missing": missing,
        "extra": extra,
        "aligned": len(missing) == 0,
    }
    return report


def sync_results(method: str, lang: str, dry_run: bool = False, allow_official: bool = False) -> dict:
    """将 {method} 的结果复制到 {method}_en。"""
    if lang != "en":
        return {"synced": 0, "skipped": 0, "error": "sync only needed for --lang en"}

    ct_root = PROJECT_ROOT / "ChinaTravel"
    src_dir = ct_root / "results" / method
    dst_dir = ct_root / "results" / (method + "_en")
    if dst_dir.name == "TPCAgent_TPCLLM_en" and not allow_official:
        return {
            "synced": 0,
            "skipped": 0,
            "errors": 0,
            "error": "refusing to sync into protected TPCAgent_TPCLLM_en without --allow-official",
            "src": str(src_dir),
            "dst": str(dst_dir),
            "dry_run": dry_run,
        }

    if not src_dir.exists():
        return {"synced": 0, "skipped": 0, "error": f"source dir not found: {src_dir}"}

    synced, skipped, errors = 0, 0, 0
    for src_file in sorted(src_dir.glob("*.json")):
        dst_file = dst_dir / src_file.name
        if dst_file.exists():
            skipped += 1
            continue
        if not dry_run:
            dst_dir.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(src_file, dst_file)
                synced += 1
            except OSError as e:
                errors += 1
                print(f"  ERROR: {src_file.name} -> {e}", file=sys.stderr)
        else:
            synced += 1

    if dry_run:
        print(f"[DRY RUN] would copy {synced} files, skip {skipped} existing")

    return {
        "synced": synced,
        "skipped": skipped,
        "errors": errors,
        "src": str(src_dir),
        "dst": str(dst_dir),
        "dry_run": dry_run,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Results sync & pre-eval count check")
    parser.add_argument("--check", action="store_true", help="check result count vs split")
    parser.add_argument("--sync", action="store_true", help="sync {method} -> {method}_en")
    parser.add_argument("--dry-run", action="store_true", help="dry run")
    parser.add_argument("--allow-official", action="store_true", help="allow writes into protected official result dir")
    parser.add_argument("--splits", "-s", type=str, default="easy")
    parser.add_argument("--method", "-m", type=str, default="TPCAgent_TPCLLM")
    parser.add_argument("--lang", choices=["zh", "en"], default="en")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    if args.sync:
        result = sync_results(args.method, args.lang, dry_run=args.dry_run, allow_official=args.allow_official)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if result.get("error"):
                print(f"sync blocked: {result['error']}")
            else:
                print(f"sync: {result['synced']} copied, {result['skipped']} skipped, {result['errors']} errors")

    if args.check:
        report = check_counts(args.splits, args.method, args.lang)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            status = "ALIGNED" if report["aligned"] else "MISMATCH"
            print(f"{status}: split={report['split_count']} available={report['available_count']} "
                  f"dir_results={report['result_count']} "
                  f"[{report['method']}] @ {report['results_dir']}")
            if report["missing"]:
                n = len(report["missing"])
                print(f"  Missing ({n}): {', '.join(report['missing'][:10])}"
                      f"{'...' if n > 10 else ''}")
            if report["extra"]:
                n = len(report["extra"])
                print(f"  Extra ({n}): {', '.join(report['extra'][:10])}"
                      f"{'...' if n > 10 else ''}")


if __name__ == "__main__":
    main()
