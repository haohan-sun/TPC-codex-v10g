"""Build an augmented JSONL training corpus for constraint extraction.

Sources:
  - generated/ml_dataset/train.jsonl and valid.jsonl
  - generated/web_entity_enrichment.jsonl, if present
  - generated/deepseek_fuzzy_augments.jsonl, if present

The validation split stays original by default, so synthetic paraphrases do not
inflate validation metrics.
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
BASE_DATASET = GENERATED / "ml_dataset"
OUT_DIR = GENERATED / "ml_augmented_dataset"

NUMBER_WORDS = {
    "1": ["1", "one", "solo"],
    "2": ["2", "two", "a pair of"],
    "3": ["3", "three"],
    "4": ["4", "four"],
    "5": ["5", "five"],
}

WEB_TYPE_TO_LABEL = {
    "theme_park": "attraction_types:amusement_park/sports_entertainment",
    "amusement_park": "attraction_types:amusement_park/sports_entertainment",
    "museum": "attraction_types:museum/memorial_hall",
    "artwork": "attraction_types:art_museum",
    "gallery": "attraction_types:art_museum",
    "park": "attraction_types:park",
    "garden": "attraction_types:park",
    "attraction": "attraction_types:other",
    "viewpoint": "attraction_types:natural_scenery",
    "nature_reserve": "attraction_types:natural_scenery",
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    if not path.exists():
        return rows
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


def label_value(labels: list[str], prefix: str) -> str:
    for label in labels:
        if label.startswith(prefix + ":"):
            return label.split(":", 1)[1]
    return ""


def values(labels: list[str], prefix: str) -> list[str]:
    return [label.split(":", 1)[1] for label in labels if label.startswith(prefix + ":")]


def phrase(value: str) -> str:
    return value.replace("_", " ").replace("/", " or ")


def count_phrase(value: str, kind: str, variant: int) -> str:
    choices = NUMBER_WORDS.get(value, [value])
    picked = choices[variant % len(choices)]
    if kind == "people":
        if picked == "solo":
            return "I am traveling alone"
        if picked.startswith("a pair"):
            return "a pair of us are traveling"
        return f"we are {picked} people"
    if picked.startswith("a pair"):
        picked = "two"
    return f"for {picked} days"


def summarize_constraints(labels: list[str], variant: int) -> list[str]:
    chunks: list[str] = []
    must_visit = values(labels, "must_visit")[:2]
    forbidden_pois = values(labels, "forbidden_pois")[:2]
    attraction_types = values(labels, "attraction_types")[:2]
    forbidden_attraction_types = values(labels, "forbidden_attraction_types")[:2]
    restaurant_names = values(labels, "restaurant_names")[:2]
    restaurant_types = values(labels, "restaurant_types")[:2]
    forbidden_restaurant_types = values(labels, "forbidden_restaurant_types")[:2]
    hotel_names = values(labels, "hotel_names")[:2]
    hotel_features = values(labels, "hotel_features")[:2]
    budget_kinds = values(labels, "budget_kinds")[:2]
    required_inner = values(labels, "required_inner_transport")[:2]
    required_intercity = values(labels, "required_intercity_transport")[:2]
    forbidden_inner = values(labels, "forbidden_inner_transport")[:2]
    forbidden_intercity = values(labels, "forbidden_intercity_transport")[:2]

    if must_visit:
        templates = [
            "make sure to include {}",
            "{} should be on the itinerary",
            "do not miss {}",
        ]
        chunks.append(templates[variant % len(templates)].format(" and ".join(phrase(v) for v in must_visit)))
    if forbidden_pois:
        chunks.append("avoid visiting {}".format(" and ".join(phrase(v) for v in forbidden_pois)))
    if attraction_types:
        chunks.append("add a {} style attraction".format(" or ".join(phrase(v) for v in attraction_types)))
    if forbidden_attraction_types:
        chunks.append("skip {} style attractions".format(" or ".join(phrase(v) for v in forbidden_attraction_types)))
    if restaurant_names:
        chunks.append("try dining at {}".format(" or ".join(phrase(v) for v in restaurant_names)))
    if restaurant_types:
        chunks.append("meals can lean toward {}".format(" or ".join(phrase(v) for v in restaurant_types)))
    if forbidden_restaurant_types:
        chunks.append("avoid {} restaurants".format(" or ".join(phrase(v) for v in forbidden_restaurant_types)))
    if hotel_names:
        chunks.append("stay at {}".format(" or ".join(phrase(v) for v in hotel_names)))
    if hotel_features:
        chunks.append("the hotel should feel like {}".format(" or ".join(phrase(v) for v in hotel_features)))
    if budget_kinds:
        chunks.append("watch the {} budget".format(" and ".join(phrase(v) for v in budget_kinds)))
    if required_inner:
        chunks.append("local transport should use {}".format(" or ".join(phrase(v) for v in required_inner)))
    if required_intercity:
        chunks.append("intercity travel should use {}".format(" or ".join(phrase(v) for v in required_intercity)))
    if forbidden_inner:
        chunks.append("avoid local {}".format(" or ".join(phrase(v) for v in forbidden_inner)))
    if forbidden_intercity:
        chunks.append("avoid intercity {}".format(" or ".join(phrase(v) for v in forbidden_intercity)))
    if "free_attraction" in labels:
        chunks.append("prefer free attractions")
    if "free_intercity" in labels:
        chunks.append("keep intercity transport free if possible")
    if "hotel_distance" in labels:
        chunks.append("keep the hotel close to the requested anchor")
    if "activity_time_window" in labels:
        chunks.append("respect the requested arrival or leaving time")
    if "distance_taxi_rule" in labels:
        chunks.append("use taxi when local distance is too long")
    return chunks


def augment_row(row: dict[str, Any], variants: int) -> list[dict[str, Any]]:
    labels = list(row.get("labels") or [])
    people = label_value(labels, "people_count")
    days = label_value(labels, "day_count")
    out = [{**row, "source": row.get("source", "official_original")}]
    for i in range(variants):
        intro = []
        if people:
            intro.append(count_phrase(people, "people", i))
        if days:
            intro.append(count_phrase(days, "days", i))
        constraints = summarize_constraints(labels, i)
        if not intro and not constraints:
            continue
        if i % 3 == 0:
            text = ". ".join(intro + ["Requirements: " + "; ".join(constraints)]) + "."
        elif i % 3 == 1:
            text = "Please plan a trip where " + ", ".join(intro + constraints) + "."
        else:
            text = "The schedule can be flexible, but " + "; ".join(intro + constraints) + "."
        out.append(
            {
                "uid": f"{row.get('uid', 'row')}#aug{i}",
                "text": re.sub(r"\s+", " ", text).strip(),
                "labels": labels,
                "source": "template_fuzzy_aug",
            }
        )
    return out


def deepseek_rows(label_vocab: set[str]) -> list[dict[str, Any]]:
    rows = []
    for path in (GENERATED / "deepseek_fuzzy_augments.jsonl", GENERATED / "deepseek_constraint_labels.jsonl"):
        for row in read_jsonl(path):
            labels = [label for label in row.get("labels", []) if label in label_vocab]
            text = row.get("text") or row.get("augmented_text") or ""
            if has_negated_must_visit(text, labels):
                continue
            if text and labels:
                rows.append(
                    {
                        "uid": row.get("uid", f"deepseek_{len(rows)}"),
                        "text": text,
                        "labels": sorted(set(labels)),
                        "source": path.stem,
                    }
                )
    return rows


NEGATION_PATTERN = re.compile(
    r"\b(?:avoid|skip|exclude|without|do\s+not|don't|dont|rather\s+not|not\s+visit|no\s+need\s+to\s+visit)\b",
    re.IGNORECASE,
)


def normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


def has_negated_must_visit(text: str, labels: list[str], window_tokens: int = 8) -> bool:
    """Drop DeepSeek paraphrases that invert weak must-visit labels.

    Some weak labels are noisy because hard-logic clauses can contain disjunction
    or negation. If a paraphrase says "avoid X" near a `must_visit:X` label, it
    is safer to exclude that synthetic row than to train the classifier on a
    direct contradiction.
    """

    must_phrases = [
        normalize_for_match(label.split(":", 1)[1].replace("_", " "))
        for label in labels
        if label.startswith("must_visit:")
    ]
    if not must_phrases or not NEGATION_PATTERN.search(text):
        return False
    norm_text = normalize_for_match(text)
    tokens = norm_text.split()
    for phrase in must_phrases:
        phrase_tokens = phrase.split()
        if not phrase_tokens:
            continue
        n = len(phrase_tokens)
        for i in range(0, max(0, len(tokens) - n + 1)):
            if tokens[i : i + n] != phrase_tokens:
                continue
            left = " ".join(tokens[max(0, i - window_tokens) : i])
            right = " ".join(tokens[i + n : min(len(tokens), i + n + 4)])
            if NEGATION_PATTERN.search(left) or NEGATION_PATTERN.search(right):
                return True
    return False


def web_rows(label_vocab: set[str], limit: int) -> list[dict[str, Any]]:
    rows = []
    for row in read_jsonl(GENERATED / "web_entity_enrichment.jsonl"):
        name = row.get("name", "")
        city = row.get("city", "")
        for item in row.get("nominatim") or []:
            raw_type = str(item.get("type") or item.get("category") or "").lower()
            label = WEB_TYPE_TO_LABEL.get(raw_type)
            if not label or label not in label_vocab:
                continue
            rows.append(
                {
                    "uid": f"web_{row.get('entity_id', len(rows))}_{raw_type}",
                    "text": f"I want a flexible trip in {city}; include something like {name}, a {raw_type.replace('_', ' ')} place.",
                    "labels": [label],
                    "source": "web_nominatim_metadata",
                }
            )
            break
        if len(rows) >= limit:
            break
    return rows


def dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for row in rows:
        key = (row.get("text", "").lower(), tuple(sorted(row.get("labels") or [])))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variants", type=int, default=4)
    parser.add_argument("--web-limit", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260612)
    args = parser.parse_args()

    base_train = read_jsonl(BASE_DATASET / "train.jsonl")
    base_valid = read_jsonl(BASE_DATASET / "valid.jsonl")
    label_vocab = json.loads((BASE_DATASET / "label_vocab.json").read_text(encoding="utf-8"))
    label_vocab_set = set(label_vocab)

    train: list[dict[str, Any]] = []
    for row in base_train:
        train.extend(augment_row(row, args.variants))
    train.extend(deepseek_rows(label_vocab_set))
    train.extend(web_rows(label_vocab_set, args.web_limit))
    train = dedupe(train)

    rng = random.Random(args.seed)
    rng.shuffle(train)
    valid = [{**row, "source": row.get("source", "official_valid")} for row in base_valid]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_jsonl(OUT_DIR / "train.jsonl", train)
    write_jsonl(OUT_DIR / "valid.jsonl", valid)
    (OUT_DIR / "label_vocab.json").write_text(json.dumps(label_vocab, ensure_ascii=False, indent=2), encoding="utf-8")
    stats = {
        "base_train": len(base_train),
        "base_valid": len(base_valid),
        "augmented_train": len(train),
        "valid": len(valid),
        "labels": len(label_vocab),
        "sources": Counter(row.get("source", "unknown") for row in train),
    }
    (OUT_DIR / "dataset_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out_dir": str(OUT_DIR), **stats}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
