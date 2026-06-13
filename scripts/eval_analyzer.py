"""Post-eval failure detail analyzer (P0.2 + P0.3).

Distinguishes three types of 0 scores and exports failure CSVs.

Usage::

    python scripts/eval_analyzer.py --splits demo1_training_single --method TPCAgent_TPCLLM --lang en --export-csv
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CT_ROOT = PROJECT_ROOT / "ChinaTravel"

if str(CT_ROOT) not in sys.path:
    sys.path.insert(0, str(CT_ROOT))


def resolve_method(method: str, lang: str) -> str:
    if lang == "en" and not method.endswith("_en"):
        method += "_en"
    return method


def load_query_data(splits: str, lang: str = "en"):
    from chinatravel.data.load_datasets import load_query

    class Args:
        pass
    a = Args()
    a.splits = splits
    a.lang = lang
    return load_query(a)


def load_result_data(method: str, query_index: list[str]) -> dict:
    results_dir = CT_ROOT / "results" / method
    plans = {}
    for qid in query_index:
        rf = results_dir / f"{qid}.json"
        if rf.exists():
            with open(rf, encoding="utf-8") as f:
                plans[qid] = json.load(f)
        else:
            plans[qid] = {}
    return plans


def check_missing(query_index: list[str], result_data: dict) -> dict:
    missing = [q for q in query_index if q not in result_data or not result_data.get(q)]
    return {
        "total": len(query_index),
        "missing": len(missing),
        "available": len(query_index) - len(missing),
        "is_type1_zero": len(missing) > 0,
        "missing_ids": missing[:20],
    }


def run_full_eval(splits: str, method: str, lang: str, quiet: bool = False) -> dict:
    from chinatravel.evaluation.schema_constraint import evaluate_schema_constraints
    from chinatravel.evaluation.commonsense_constraint import evaluate_commonsense_constraints
    from chinatravel.evaluation.hard_constraint import evaluate_hard_constraints_v2
    from eval_tpc import cal_default_pr_score

    stdout_ctx = contextlib.redirect_stdout(io.StringIO()) if quiet else contextlib.nullcontext()
    stderr_ctx = contextlib.redirect_stderr(io.StringIO()) if quiet else contextlib.nullcontext()
    with stdout_ctx, stderr_ctx:
        query_index, query_data = load_query_data(splits, lang)
    result_data = load_result_data(method, query_index)
    missing = check_missing(query_index, result_data)

    schema_path = CT_ROOT / "chinatravel" / "evaluation" / "output_schema.json"
    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)

    with stdout_ctx, stderr_ctx:
        schema_rate, schema_agg, schema_pass_id = evaluate_schema_constraints(
            query_index, result_data, schema
        )
        macro_comm, micro_comm, comm_agg, commonsense_pass_id = evaluate_commonsense_constraints(
            query_index, query_data, result_data, verbose=False, lang=lang
        )
        macro_logi, micro_logi, conditional_macro_logi, conditional_micro_logi, logi_agg, logi_pass_id = (
            evaluate_hard_constraints_v2(
                query_index,
                query_data,
                result_data,
                env_pass_id=commonsense_pass_id,
                verbose=False,
                lang=lang,
            )
        )

    all_pass_id = sorted(set(schema_pass_id) & set(commonsense_pass_id) & set(logi_pass_id))
    fpr = len(all_pass_id) / max(1, len(query_index)) * 100
    with stdout_ctx, stderr_ctx:
        pre_res = cal_default_pr_score(query_index, query_data, result_data, all_pass_id)
    dav_val = float(pre_res[0]) * 100
    att_val = float(pre_res[1]) * 100
    ddr_val = float(pre_res[2]) * 100
    c_lpr = float(conditional_micro_logi)
    overall = (
        0.2 * float(micro_comm)
        + 0.25 * c_lpr
        + 0.05 * dav_val
        + 0.05 * att_val
        + 0.05 * ddr_val
        + 0.4 * fpr
    )

    # Classify zero-score type
    if missing["is_type1_zero"]:
        zero_type = "type1_missing_results"
    elif micro_comm > 0 and not commonsense_pass_id:
        zero_type = "type2_commonsense_gate"
    elif micro_comm > 0 and commonsense_pass_id and c_lpr == 0:
        zero_type = "type3_hard_logic_or_data_mismatch"
    else:
        zero_type = "none"

    # Top failure types from commonsense agg
    failure_types = {}
    if comm_agg is not None and not comm_agg.empty:
        for col in comm_agg.columns:
            if col == "data_id":
                continue
            fc = int((comm_agg[col] == 1).sum())  # 1=FAIL, 0=PASS in commonsense agg
            if fc > 0:
                failure_types[col] = fc

    return {
        "timestamp": datetime.now().isoformat(),
        "splits": splits, "method": method, "lang": lang,
        "zero_score_type": zero_type,
        "missing_report": missing,
        "scores": {
            "MicEPR": float(micro_comm),
            "MacEPR": float(macro_comm),
            "HardMicro": float(micro_logi),
            "HardMacro": float(macro_logi),
            "C-LPR": float(c_lpr),
            "FPR": float(fpr),
            "DAV": float(dav_val),
            "ATT": float(att_val),
            "DDR": float(ddr_val),
            "overall": float(overall),
        },
        "pass_ids": {
            "schema_pass": len(schema_pass_id or []),
            "commonsense_pass": len(commonsense_pass_id or []),
            "hard_pass": len(logi_pass_id or []),
            "all_pass": len(all_pass_id),
        },
        "failures": {
            "schema_fail": len(query_index) - len(schema_pass_id or []),
            "commonsense_fail": len(query_index) - len(commonsense_pass_id or []),
            "top_failure_types": dict(sorted(failure_types.items(), key=lambda x: -x[1])[:10]),
        },
        "commonsense_pass_id": commonsense_pass_id or [],
    }, comm_agg, schema_agg


def export_csv(report, comm_agg, schema_agg, splits, method, quiet: bool = False):
    eval_dir = CT_ROOT / "eval_res" / f"splits_{splits}" / method
    eval_dir.mkdir(parents=True, exist_ok=True)
    jp = eval_dir / "failure_report.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    if not quiet:
        print(f"  Report: {jp}")
    if comm_agg is not None and not comm_agg.empty:
        cp = eval_dir / "commonsense_details.csv"
        comm_agg.to_csv(cp, index=False, encoding="utf-8-sig")
        if not quiet:
            print(f"  CSV: {cp}")
    if schema_agg is not None and not schema_agg.empty:
        sp = eval_dir / "schema_details.csv"
        schema_agg.to_csv(sp, index=False, encoding="utf-8-sig")
        if not quiet:
            print(f"  CSV: {sp}")


def main():
    parser = argparse.ArgumentParser(description="Eval failure analyzer (P0.2/P0.3)")
    parser.add_argument("--splits", "-s", type=str, default="demo1_training_single")
    parser.add_argument("--method", "-m", type=str, default="TPCAgent_TPCLLM")
    parser.add_argument("--lang", choices=["zh", "en"], default="en")
    parser.add_argument("--export-csv", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    method = resolve_method(args.method, args.lang)
    report, comm_agg, schema_agg = run_full_eval(args.splits, method, args.lang, quiet=args.json)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if args.export_csv:
            export_csv(report, comm_agg, schema_agg, args.splits, method, quiet=True)
        return

    print(f"=== Eval Analyzer: {args.splits} / {method} ===")
    print(f"Zero-score type: {report['zero_score_type']}")
    mr = report["missing_report"]
    print(f"Results: {mr['available']}/{mr['total']} available ({mr['missing']} missing)")
    print()
    for k, v in report["scores"].items():
        print(f"  {k}: {v:.1f}")
    print()
    print(f"Pass IDs: schema={report['pass_ids']['schema_pass']}, "
          f"commonsense={report['pass_ids']['commonsense_pass']}, "
          f"all={report['pass_ids']['all_pass']}")
    print(f"Failures: schema={report['failures']['schema_fail']}, "
          f"commonsense={report['failures']['commonsense_fail']}")
    if report["failures"]["top_failure_types"]:
        print("Top failure types:")
        for ft, fc in report["failures"]["top_failure_types"].items():
            print(f"  {ft}: {fc}")

    if report["zero_score_type"] == "type2_commonsense_gate":
        print("\nDIAGNOSIS: Commonsense gate blocking. Fix P1 items.")
    elif report["zero_score_type"] == "type1_missing_results":
        print("\nDIAGNOSIS: Missing results. Run the split first.")

    if args.export_csv:
        export_csv(report, comm_agg, schema_agg, args.splits, method)


if __name__ == "__main__":
    main()
