"""Export hard-logic failures aligned with semantic model predictions.

This is a lab-only sidecar. It reads a generated result split, runs the
official schema/commonsense/hard verifiers, and saves per-query hard failures
plus the current semantic classifier predictions.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = LAB_ROOT.parent
DEFAULT_WORKTREE = PROJECT_ROOT / "recovery_lab" / "codex_worktrees" / "codex_rescue_v1"
ACTIVE_MODEL = LAB_ROOT / "generated" / "models" / "active_constraint_model.json"
OUT_ROOT = LAB_ROOT / "generated" / "v9_semantic_alignment"
EXCLUSIVE_PREFIXES = {"people_count", "day_count", "ticket_count", "taxi_cars", "metro_tickets"}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def tokenize(text: str, ngram_max: int = 1) -> list[str]:
    words = [t for t in re.findall(r"[A-Za-z0-9]+", text.lower()) if len(t) > 1]
    tokens = list(words)
    for n in range(2, max(1, ngram_max) + 1):
        tokens.extend("__".join(words[i : i + n]) for i in range(0, max(0, len(words) - n + 1)))
    return tokens


def default_model_dir() -> Path:
    data = load_json(ACTIVE_MODEL)
    model_dir = Path(data["model_dir"])
    if not model_dir.is_absolute():
        model_dir = PROJECT_ROOT / model_dir
    return model_dir


def load_predictor(model_dir: Path):
    import torch
    import torch.nn as nn

    words = load_json(model_dir / "word_vocab.json")
    labels = load_json(model_dir / "label_vocab.json")
    tokenizer_config = load_json(model_dir / "tokenizer_config.json") if (model_dir / "tokenizer_config.json").exists() else {}
    summary = load_json(model_dir / "training_summary.json")
    ngram_max = int(tokenizer_config.get("ngram_max", summary.get("ngram_max", 1)))
    threshold = float(summary.get("best", {}).get("threshold", 0.5))
    state = torch.load(model_dir / "model.pt", map_location="cpu")
    hidden = state["0.weight"].shape[0]
    model = nn.Sequential(
        nn.Linear(len(words), hidden),
        nn.ReLU(),
        nn.Dropout(0.0),
        nn.Linear(hidden, len(labels)),
    )
    model.load_state_dict(state)
    model.eval()
    return {
        "torch": torch,
        "model": model,
        "words": words,
        "labels": labels,
        "word_to_idx": {word: i for i, word in enumerate(words)},
        "ngram_max": ngram_max,
        "threshold": threshold,
        "model_dir": str(model_dir),
    }


def predict_labels(text: str, predictor: dict[str, Any], top_k: int) -> dict[str, Any]:
    torch = predictor["torch"]
    word_to_idx = predictor["word_to_idx"]
    vec = torch.zeros(len(word_to_idx), dtype=torch.float32)
    for token in tokenize(text, predictor["ngram_max"]):
        idx = word_to_idx.get(token)
        if idx is not None:
            vec[idx] += 1.0
    if vec.sum() > 0:
        vec = torch.log1p(vec)
    with torch.no_grad():
        probs = torch.sigmoid(predictor["model"](vec.unsqueeze(0)))[0]
    ranked = sorted(
        (
            {"label": label, "probability": float(probs[i])}
            for i, label in enumerate(predictor["labels"])
        ),
        key=lambda row: row["probability"],
        reverse=True,
    )
    selected: list[dict[str, Any]] = []
    best_exclusive: dict[str, dict[str, Any]] = {}
    for row in ranked:
        prefix = row["label"].split(":", 1)[0]
        if prefix in EXCLUSIVE_PREFIXES:
            if row["probability"] >= predictor["threshold"]:
                old = best_exclusive.get(prefix)
                if old is None or row["probability"] > old["probability"]:
                    best_exclusive[prefix] = row
        elif row["probability"] >= predictor["threshold"]:
            selected.append(row)
    selected.extend(best_exclusive.values())
    selected.sort(key=lambda row: row["probability"], reverse=True)
    return {
        "threshold": predictor["threshold"],
        "top": ranked[:top_k],
        "selected": selected,
    }


def categorize_logic(logic: str) -> str:
    low = logic.lower()
    if "day_count" in low or "days" in low:
        return "day_count"
    if "people_count" in low or "people_number" in low:
        return "people_count"
    if "activity_tickets" in low or "tickets" in low or "metro_tickets" in low:
        return "tickets"
    if "taxi_cars" in low:
        return "taxi_cars"
    if "intercity_transport" in low:
        return "intercity_transport"
    if "inner_city_transportation_cost" in low:
        return "innercity_transport_budget"
    if "innercity_transport" in low or "transport_type" in low:
        return "innercity_transport"
    if "attraction_name" in low or "attraction_names" in low or "must_visit" in low:
        return "attraction_name"
    if "spot_type" in low or "attraction_type" in low:
        return "attraction_type"
    if "hotel_name" in low or "hotel_names" in low or "accommodation_name" in low:
        return "hotel_name"
    if "hotel_feature" in low or "accommodation_type" in low:
        return "hotel_feature"
    if "accommodation_position" in low or "poi_distance" in low:
        return "hotel_distance"
    if "room_type" in low:
        return "room_type"
    if "room_count" in low or "rooms" in low:
        return "room_count"
    if "restaurant_name" in low or "restaurant_names" in low:
        return "restaurant_name"
    if "food_type" in low or "restaurant_type" in low:
        return "food_type"
    if "activity_end_time" in low or "activity_start_time" in low:
        return "activity_time_window"
    if "cost" in low or "price" in low or "budget" in low:
        return "budget"
    return "other"


def label_family(label: str) -> str:
    prefix = label.split(":", 1)[0]
    value = label.split(":", 1)[1] if ":" in label else ""
    if prefix == "budget_kinds" and value == "innercity_transport":
        return "innercity_transport_budget"
    mapping = {
        "attraction_types": "attraction_type",
        "forbidden_attraction_types": "attraction_type",
        "must_visit": "attraction_name",
        "forbidden_pois": "attraction_name",
        "hotel_names": "hotel_name",
        "hotel_features": "hotel_feature",
        "room_type": "room_type",
        "room_count": "room_count",
        "hotel_distance": "hotel_distance",
        "restaurant_names": "restaurant_name",
        "restaurant_types": "food_type",
        "forbidden_restaurant_names": "restaurant_name",
        "forbidden_restaurant_types": "food_type",
        "intercity_transport": "intercity_transport",
        "forbidden_intercity_transport": "intercity_transport",
        "innercity_transport": "innercity_transport",
        "budget_kinds": "budget",
        "day_count": "day_count",
        "people_count": "people_count",
        "ticket_count": "tickets",
        "taxi_cars": "taxi_cars",
        "metro_tickets": "tickets",
    }
    return mapping.get(prefix, prefix)


def load_results(query_index: list[str], results_dir: Path) -> dict[str, dict[str, Any]]:
    out = {}
    for uid in query_index:
        path = results_dir / f"{uid}.json"
        out[uid] = load_json(path) if path.exists() else {}
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", default=str(DEFAULT_WORKTREE))
    parser.add_argument("--split", default="codex_rand30_s131")
    parser.add_argument("--method", default="CODEX_V9_TPCLLM_en")
    parser.add_argument("--lang", default="en", choices=["en", "zh"])
    parser.add_argument("--model-dir", default="")
    parser.add_argument("--top-k", type=int, default=12)
    args = parser.parse_args()

    worktree = Path(args.worktree)
    china = worktree / "ChinaTravel"
    sys.path.insert(0, str(china))

    from chinatravel.data.load_datasets import load_query
    from chinatravel.evaluation.commonsense_constraint import evaluate_commonsense_constraints
    from chinatravel.evaluation.hard_constraint import evaluate_hard_constraints_v2
    from chinatravel.evaluation.schema_constraint import evaluate_schema_constraints
    from chinatravel.evaluation.utils import load_json_file

    query_args = SimpleNamespace(splits=args.split, lang=args.lang)
    query_index, query_data = load_query(query_args)
    results_dir = china / "results" / args.method
    result_data = load_results(query_index, results_dir)
    schema = load_json_file(str(china / "chinatravel" / "evaluation" / "output_schema.json"))

    schema_rate, _, schema_pass_id = evaluate_schema_constraints(query_index, result_data, schema=schema)
    macro_comm, micro_comm, _, commonsense_pass_id = evaluate_commonsense_constraints(
        query_index, query_data, result_data, verbose=False, lang=args.lang
    )
    macro_logi, micro_logi, conditional_macro, conditional_micro, logi_result_agg, logi_pass_id = (
        evaluate_hard_constraints_v2(
            query_index, query_data, result_data, env_pass_id=commonsense_pass_id, verbose=False, lang=args.lang
        )
    )

    predictor = load_predictor(Path(args.model_dir) if args.model_dir else default_model_dir())
    out_dir = OUT_ROOT / args.split / args.method
    out_dir.mkdir(parents=True, exist_ok=True)

    schema_pass = set(schema_pass_id)
    comm_pass = set(commonsense_pass_id)
    hard_pass = set(logi_pass_id)
    all_pass = schema_pass & comm_pass & hard_pass

    rows: list[dict[str, Any]] = []
    jsonl_rows: list[dict[str, Any]] = []
    category_counts: dict[str, int] = {}
    semantic_hits = 0
    semantic_checks = 0

    logi_by_id = {str(row["data_id"]): row for _, row in logi_result_agg.iterrows()}
    for uid in query_index:
        query = query_data[uid]
        text = query.get("nature_language", "")
        hard_logic = list(query.get("hard_logic_py") or [])
        pred = predict_labels(text, predictor, args.top_k)
        selected_families = {label_family(row["label"]) for row in pred["selected"]}
        logi_row = logi_by_id.get(uid)
        failing = []
        if logi_row is not None:
            for idx, logic in enumerate(hard_logic):
                col = f"logic_py_{idx}"
                if int(logi_row.get(col, 0) or 0) == 0:
                    category = categorize_logic(logic)
                    category_counts[category] = category_counts.get(category, 0) + 1
                    semantic_checks += 1
                    hit = category in selected_families
                    semantic_hits += int(hit)
                    failing.append(
                        {
                            "logic_index": idx,
                            "category": category,
                            "semantic_family_hit": hit,
                            "logic": logic,
                        }
                    )
        row = {
            "data_id": uid,
            "schema_pass": uid in schema_pass,
            "commonsense_pass": uid in comm_pass,
            "hard_pass": uid in hard_pass,
            "all_pass": uid in all_pass,
            "failure_count": len(failing),
            "failure_categories": "|".join(sorted({f["category"] for f in failing})),
            "selected_labels": "|".join(row["label"] for row in pred["selected"][: args.top_k]),
            "top_labels": "|".join(f'{row["label"]}:{row["probability"]:.3f}' for row in pred["top"][: args.top_k]),
            "text": text,
        }
        rows.append(row)
        jsonl_rows.append(
            {
                **row,
                "failing_logic": failing,
                "predictions": pred,
                "hard_logic_py": hard_logic,
            }
        )

    csv_path = out_dir / "semantic_hard_alignment.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    jsonl_path = out_dir / "semantic_hard_alignment.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for row in jsonl_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = {
        "split": args.split,
        "method": args.method,
        "schema_rate": schema_rate,
        "micro_commonsense": micro_comm,
        "macro_commonsense": macro_comm,
        "hard_micro": micro_logi,
        "hard_macro": macro_logi,
        "conditional_hard_micro": conditional_micro,
        "conditional_hard_macro": conditional_macro,
        "schema_pass": len(schema_pass),
        "commonsense_pass": len(comm_pass),
        "hard_pass": len(hard_pass),
        "all_pass": len(all_pass),
        "total": len(query_index),
        "category_counts": dict(sorted(category_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "semantic_family_hit_rate": semantic_hits / semantic_checks if semantic_checks else None,
        "semantic_hits": semantic_hits,
        "semantic_checks": semantic_checks,
        "model": predictor["model_dir"],
        "threshold": predictor["threshold"],
        "csv": str(csv_path),
        "jsonl": str(jsonl_path),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "summary.md").write_text(
        "# V9 Semantic Alignment\n\n"
        f"- Split: `{args.split}`\n"
        f"- Method: `{args.method}`\n"
        f"- Schema pass: {len(schema_pass)}/{len(query_index)}\n"
        f"- Commonsense pass: {len(comm_pass)}/{len(query_index)}\n"
        f"- Hard pass: {len(hard_pass)}/{len(query_index)}\n"
        f"- All pass: {len(all_pass)}/{len(query_index)}\n"
        f"- Conditional hard micro: {conditional_micro:.2f}\n"
        f"- Semantic family hit rate on failing logic: {summary['semantic_family_hit_rate']}\n\n"
        "## Failing Logic Categories\n\n"
        + "\n".join(f"- {k}: {v}" for k, v in summary["category_counts"].items())
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
