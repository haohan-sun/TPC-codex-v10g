"""Fast isolated robustness run with per-day scoring.

This script is intentionally independent from official result directories.
It runs a bounded batch, reuses existing valid JSON where possible, and writes
per-query plus per-day score tables for quick robustness auditing.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_ROOT = PROJECT_ROOT / "ChinaTravel" / "results"
OUTPUTS_ROOT = PROJECT_ROOT / "data" / "outputs"


def _read_ids(split: str) -> list[str]:
    split_path = PROJECT_ROOT / "data" / "splits" / f"{split}.txt"
    if not split_path.exists():
        raise FileNotFoundError(f"split not found: {split_path}")
    return [x for x in split_path.read_text(encoding="utf-8").split() if x and not x.startswith("#")]


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) and data.get("itinerary") else None


def _clean_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in plan.items()
        if not k.startswith("_") and k not in {"error", "score", "metadata", "budget_report"}
    }


def _normalize_itinerary(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [d for d in value if isinstance(d, dict)]
    if not isinstance(value, dict):
        return []
    day_items: list[tuple[int, dict[str, Any]]] = []
    for key, item in value.items():
        if not isinstance(item, dict):
            continue
        if "activities" not in item:
            continue
        try:
            day_no = int(key)
        except Exception:
            try:
                day_no = int(item.get("day", len(day_items) + 1))
            except Exception:
                day_no = len(day_items) + 1
        day_items.append((day_no, item))
    return [item for _, item in sorted(day_items, key=lambda pair: pair[0])]


def _worker(uid: str, result_dir: Path, status_dir: Path) -> int:
    started = time.time()
    status = {
        "query_id": uid,
        "status": "unknown",
        "seconds": 0.0,
        "days": 0,
        "activities": 0,
        "error": "",
    }
    try:
        os.environ.setdefault("TPC_FAST_MODE", "1")
        sys.path.insert(0, str(PROJECT_ROOT))
        from src.data_layer.loaders import query_from_dict
        from main import solve_one_query

        qpath = PROJECT_ROOT / "data" / "training data" / f"{uid}.json"
        raw = json.loads(qpath.read_text(encoding="utf-8"))
        raw["uid"] = uid
        plan = _clean_plan(solve_one_query(query_from_dict(raw)))
        itinerary = _normalize_itinerary(plan.get("itinerary", []))
        plan["itinerary"] = itinerary
        if not isinstance(itinerary, list) or not itinerary:
            raise ValueError("empty itinerary")
        result_dir.mkdir(parents=True, exist_ok=True)
        (result_dir / f"{uid}.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        status["status"] = "ok"
        status["days"] = len(itinerary)
        status["activities"] = sum(len(d.get("activities", [])) for d in itinerary if isinstance(d, dict))
    except Exception as exc:
        status["status"] = "error"
        status["error"] = f"{type(exc).__name__}: {str(exc)[:240]}"
    status["seconds"] = round(time.time() - started, 2)
    status_dir.mkdir(parents=True, exist_ok=True)
    (status_dir / f"{uid}.json").write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
    return 0 if status["status"] == "ok" else 1


def _minutes(value: Any) -> int | None:
    if not isinstance(value, str) or ":" not in value:
        return None
    value = value.split("次日")[-1]
    try:
        h, m = value.split(":")[:2]
        return int(h) * 60 + int(m)
    except Exception:
        return None


def _activity_position(activity: dict[str, Any]) -> str:
    return str(activity.get("position") or activity.get("end") or activity.get("start") or "")


def _transport_minutes(activity: dict[str, Any]) -> int:
    total = 0
    for trans in activity.get("transports") or []:
        st = _minutes(trans.get("start_time"))
        ed = _minutes(trans.get("end_time"))
        if st is not None and ed is not None and ed >= st:
            total += ed - st
    return total


def _day_score(day: dict[str, Any]) -> dict[str, Any]:
    activities = [a for a in day.get("activities", []) if isinstance(a, dict)]
    attraction_count = sum(1 for a in activities if a.get("type") == "attraction")
    meal_count = sum(1 for a in activities if a.get("type") in {"breakfast", "lunch", "dinner"})
    transport_acts = sum(1 for a in activities if a.get("transports"))
    transport_minutes = sum(_transport_minutes(a) for a in activities)
    avg_transport = transport_minutes / transport_acts if transport_acts else 0.0

    time_order_ok = 1
    prev_end = None
    missing_time = 0
    for activity in activities:
        st = _minutes(activity.get("start_time"))
        ed = _minutes(activity.get("end_time"))
        if st is None or ed is None:
            missing_time += 1
            time_order_ok = 0
            continue
        if activity.get("type") not in {"train", "airplane"} and ed <= st:
            time_order_ok = 0
        if prev_end is not None and st < prev_end and activity.get("type") not in {"train", "airplane"}:
            time_order_ok = 0
        prev_end = ed

    text = json.dumps(day, ensure_ascii=False)
    no_leak = not any(key in text for key in ["_internal", "metadata", "budget_report", "debug"])
    no_fake_id = "TR_" not in text and "FL_" not in text
    unique_attractions = len(
        {
            _activity_position(a)
            for a in activities
            if a.get("type") == "attraction" and _activity_position(a)
        }
    )

    time_score = 20.0 if time_order_ok else 0.0
    meal_score = min(meal_count / 3.0, 1.0) * 20.0
    attraction_score = min(attraction_count / 4.0, 1.0) * 20.0
    if transport_acts == 0:
        transport_score = 20.0
    else:
        transport_score = max(0.0, min(20.0, 20.0 * (1.0 - max(avg_transport - 15.0, 0.0) / 90.0)))
    hygiene_score = (5.0 if no_leak else 0.0) + (5.0 if no_fake_id else 0.0)
    richness_score = min(len(activities) / 6.0, 1.0) * 10.0
    day_score = round(time_score + meal_score + attraction_score + transport_score + hygiene_score + richness_score, 2)

    return {
        "day": day.get("day", ""),
        "score": day_score,
        "activities": len(activities),
        "attractions": attraction_count,
        "unique_attractions": unique_attractions,
        "meals": meal_count,
        "transport_activities": transport_acts,
        "transport_minutes": transport_minutes,
        "avg_transport_minutes": round(avg_transport, 2),
        "time_order_ok": time_order_ok,
        "missing_time": missing_time,
        "no_debug_leak": int(no_leak),
        "no_fake_id": int(no_fake_id),
    }


def _score_plan(uid: str, plan: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    itinerary = _normalize_itinerary(plan.get("itinerary", []))
    day_rows = []
    for idx, day in enumerate(itinerary, 1):
        if not isinstance(day, dict):
            continue
        row = {"query_id": uid, **_day_score(day)}
        if row["day"] == "":
            row["day"] = idx
        day_rows.append(row)
    avg_score = round(sum(r["score"] for r in day_rows) / len(day_rows), 2) if day_rows else 0.0
    summary = {
        "query_id": uid,
        "status": "scored" if day_rows else "empty",
        "days": len(day_rows),
        "avg_day_score": avg_score,
        "min_day_score": min((r["score"] for r in day_rows), default=0.0),
        "activities": sum(r["activities"] for r in day_rows),
        "attractions": sum(r["attractions"] for r in day_rows),
        "meals": sum(r["meals"] for r in day_rows),
        "time_order_fail_days": sum(1 for r in day_rows if not r["time_order_ok"]),
    }
    return summary, day_rows


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _markdown_table(rows: list[dict[str, Any]], fields: list[str], limit: int = 60) -> str:
    rows = rows[:limit]
    out = ["|" + "|".join(fields) + "|", "|" + "|".join(["---"] * len(fields)) + "|"]
    for row in rows:
        out.append("|" + "|".join(str(row.get(f, "")) for f in fields) + "|")
    return "\n".join(out)


def _run_parent(args: argparse.Namespace) -> int:
    started = time.time()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUTPUTS_ROOT / f"fast_day_eval_{stamp}"
    result_dir = RESULTS_ROOT / f"{args.method}_en"
    status_dir = out_dir / "status"
    result_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    ids = _read_ids(args.split)
    deadline = started + args.minutes * 60
    reuse_dirs = [
        RESULTS_ROOT / "TPCAgent_TPCLLM_en",
        RESULTS_ROOT / "TEMP_BATCH_50_en",
        RESULTS_ROOT / "TEMP_BATCH_1000_en",
        RESULTS_ROOT / "TPCAgent_BATCH50_en",
        PROJECT_ROOT / "data" / "outputs" / "archive" / "current_stable_official_en",
    ]

    query_rows: list[dict[str, Any]] = []
    reused = 0
    pending: list[str] = []
    for uid in ids:
        target = result_dir / f"{uid}.json"
        plan = _load_json(target)
        source = "generated_existing" if plan else ""
        if plan is None and args.reuse:
            for directory in reuse_dirs:
                candidate = directory / f"{uid}.json"
                plan = _load_json(candidate)
                if plan is not None:
                    target.write_text(json.dumps(_clean_plan(plan), ensure_ascii=False, indent=2), encoding="utf-8")
                    source = directory.name
                    reused += 1
                    break
        if plan is None:
            pending.append(uid)
        else:
            query_rows.append({"query_id": uid, "generation_status": "reused", "source": source, "seconds": 0.0, "error": ""})

    running: dict[str, subprocess.Popen[str]] = {}
    start_times: dict[str, float] = {}
    pending_iter = iter(pending)
    finished_status: dict[str, dict[str, Any]] = {}

    def launch(uid: str) -> None:
        cmd = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            uid,
            "--result-dir",
            str(result_dir),
            "--status-dir",
            str(status_dir),
        ]
        env = os.environ.copy()
        env["TPC_FAST_MODE"] = "1"
        running[uid] = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        start_times[uid] = time.time()

    while time.time() < deadline and (pending or running):
        while len(running) < args.workers and pending and time.time() < deadline:
            uid = pending.pop(0)
            launch(uid)
        time.sleep(0.25)
        for uid, proc in list(running.items()):
            elapsed = time.time() - start_times[uid]
            if proc.poll() is not None:
                status_path = status_dir / f"{uid}.json"
                status = _load_json(status_path) or {}
                if not status:
                    try:
                        status = json.loads(status_path.read_text(encoding="utf-8"))
                    except Exception:
                        status = {"query_id": uid, "status": "error", "seconds": round(elapsed, 2), "error": "missing worker status"}
                finished_status[uid] = status
                running.pop(uid, None)
                start_times.pop(uid, None)
            elif elapsed > args.per_query_timeout:
                proc.kill()
                finished_status[uid] = {
                    "query_id": uid,
                    "status": "timeout",
                    "seconds": round(elapsed, 2),
                    "error": f"timeout>{args.per_query_timeout}s",
                }
                running.pop(uid, None)
                start_times.pop(uid, None)

    for uid, proc in list(running.items()):
        proc.kill()
        finished_status[uid] = {
            "query_id": uid,
            "status": "timeout",
            "seconds": round(time.time() - start_times[uid], 2),
            "error": "global deadline reached",
        }

    for uid in pending:
        finished_status[uid] = {
            "query_id": uid,
            "status": "not_started",
            "seconds": 0.0,
            "error": "global deadline reached",
        }

    for uid in ids:
        if any(r["query_id"] == uid for r in query_rows):
            continue
        status = finished_status.get(uid, {"status": "missing", "seconds": 0.0, "error": "no status"})
        query_rows.append(
            {
                "query_id": uid,
                "generation_status": status.get("status", "missing"),
                "source": "worker",
                "seconds": status.get("seconds", 0.0),
                "error": status.get("error", ""),
            }
        )

    score_summaries: list[dict[str, Any]] = []
    day_rows: list[dict[str, Any]] = []
    for uid in ids:
        plan = _load_json(result_dir / f"{uid}.json")
        if plan is None:
            continue
        summary, rows = _score_plan(uid, plan)
        score_summaries.append(summary)
        day_rows.extend(rows)

    query_by_id = {r["query_id"]: r for r in query_rows}
    score_by_id = {r["query_id"]: r for r in score_summaries}
    merged_rows = []
    for uid in ids:
        merged = {
            "query_id": uid,
            **query_by_id.get(uid, {"generation_status": "missing", "source": "", "seconds": 0.0, "error": ""}),
            **score_by_id.get(
                uid,
                {
                    "status": "unscored",
                    "days": 0,
                    "avg_day_score": 0.0,
                    "min_day_score": 0.0,
                    "activities": 0,
                    "attractions": 0,
                    "meals": 0,
                    "time_order_fail_days": 0,
                },
            ),
        }
        merged_rows.append(merged)

    _write_csv(
        out_dir / "query_summary.csv",
        merged_rows,
        [
            "query_id",
            "generation_status",
            "source",
            "seconds",
            "status",
            "days",
            "avg_day_score",
            "min_day_score",
            "activities",
            "attractions",
            "meals",
            "time_order_fail_days",
            "error",
        ],
    )
    _write_csv(
        out_dir / "day_scores.csv",
        day_rows,
        [
            "query_id",
            "day",
            "score",
            "activities",
            "attractions",
            "unique_attractions",
            "meals",
            "transport_activities",
            "transport_minutes",
            "avg_transport_minutes",
            "time_order_ok",
            "missing_time",
            "no_debug_leak",
            "no_fake_id",
        ],
    )

    completed = sum(1 for r in merged_rows if r["status"] == "scored")
    ok_generated = sum(1 for r in merged_rows if r["generation_status"] in {"ok", "reused"})
    avg_day = round(sum(r["score"] for r in day_rows) / len(day_rows), 2) if day_rows else 0.0
    summary = {
        "split": args.split,
        "method": f"{args.method}_en",
        "total_queries": len(ids),
        "scored_queries": completed,
        "generated_or_reused": ok_generated,
        "reused": reused,
        "day_rows": len(day_rows),
        "avg_day_score": avg_day,
        "elapsed_seconds": round(time.time() - started, 2),
        "result_dir": str(result_dir),
        "output_dir": str(out_dir),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    top_low = sorted(day_rows, key=lambda r: r["score"])[:20]
    md = [
        "# Fast Day Eval Summary",
        "",
        _markdown_table([summary], list(summary.keys()), limit=1),
        "",
        "## Lowest Day Scores",
        "",
        _markdown_table(
            top_low,
            [
                "query_id",
                "day",
                "score",
                "activities",
                "attractions",
                "meals",
                "avg_transport_minutes",
                "time_order_ok",
            ],
            limit=20,
        ),
    ]
    (out_dir / "summary.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if completed == len(ids) else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="training_50")
    parser.add_argument("--method", default="FAST_DAY_EVAL")
    parser.add_argument("--minutes", type=float, default=10.0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--per-query-timeout", type=float, default=45.0)
    parser.add_argument("--reuse", action="store_true", default=True)
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    parser.add_argument("--result-dir", help=argparse.SUPPRESS)
    parser.add_argument("--status-dir", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        return _worker(args.worker, Path(args.result_dir), Path(args.status_dir))
    return _run_parent(args)


if __name__ == "__main__":
    raise SystemExit(main())
