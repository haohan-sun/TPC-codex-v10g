"""Prepare a weakly-supervised dataset for deep-learning constraint extraction.

The model target is not a route plan. It is a multi-label semantic constraint
vector derived from hard_logic_py weak labels.
"""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter
from pathlib import Path
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
GENERATED = LAB_ROOT / "generated"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def normalize_label(value: str) -> str:
    value = re.sub(r"\s+", "_", str(value).strip().lower())
    value = re.sub(r"[^a-z0-9_:/.-]+", "", value)
    return value[:80]


def row_labels(row: dict[str, Any]) -> list[str]:
    labels = row.get("labels") or {}
    out: set[str] = set()
    for key in (
        "must_visit",
        "forbidden_pois",
        "attraction_types",
        "forbidden_attraction_types",
        "restaurant_names",
        "forbidden_restaurant_names",
        "restaurant_types",
        "forbidden_restaurant_types",
        "hotel_names",
        "hotel_features",
        "budget_kinds",
        "required_inner_transport",
        "required_intercity_transport",
        "forbidden_inner_transport",
        "forbidden_intercity_transport",
    ):
        for value in labels.get(key) or []:
            out.add(f"{key}:{normalize_label(value)}")
    for key in (
        "free_attraction",
        "free_intercity",
        "hotel_distance",
        "activity_time_window",
        "distance_taxi_rule",
    ):
        if labels.get(key):
            out.add(key)
    for key in (
        "people_count",
        "day_count",
        "ticket_count",
        "taxi_cars",
        "metro_tickets",
        "room_type",
        "room_count",
    ):
        if labels.get(key) is not None:
            out.add(f"{key}:{labels[key]}")
    return sorted(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-label-count", type=int, default=2)
    parser.add_argument("--valid-ratio", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=20260612)
    args = parser.parse_args()

    rows = read_jsonl(GENERATED / "hard_logic_labels.jsonl")
    prepared = []
    counts = Counter()
    for row in rows:
        labels = row_labels(row)
        counts.update(labels)
        prepared.append({"uid": row["uid"], "text": row["text"], "labels": labels})
    vocab = sorted(label for label, count in counts.items() if count >= args.min_label_count)
    vocab_set = set(vocab)
    filtered = []
    for row in prepared:
        labels = [label for label in row["labels"] if label in vocab_set]
        if labels:
            filtered.append({**row, "labels": labels})

    rng = random.Random(args.seed)
    rng.shuffle(filtered)
    valid_n = max(1, int(len(filtered) * args.valid_ratio))
    valid = filtered[:valid_n]
    train = filtered[valid_n:]

    out_dir = GENERATED / "ml_dataset"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(out_dir / "train.jsonl", train)
    write_jsonl(out_dir / "valid.jsonl", valid)
    (out_dir / "label_vocab.json").write_text(json.dumps(vocab, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "dataset_stats.json").write_text(
        json.dumps(
            {
                "source_rows": len(rows),
                "usable_rows": len(filtered),
                "train_rows": len(train),
                "valid_rows": len(valid),
                "label_vocab": len(vocab),
                "top_labels": counts.most_common(30),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"out_dir": str(out_dir), "train": len(train), "valid": len(valid), "labels": len(vocab)}, indent=2))


if __name__ == "__main__":
    main()
