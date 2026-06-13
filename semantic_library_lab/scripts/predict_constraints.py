"""Run the optional PyTorch constraint classifier on one query.

This is a lab-only inference helper. It loads the model saved by
train_constraint_classifier.py and prints predicted weak-label constraints.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
GENERATED = LAB_ROOT / "generated"
DEFAULT_MODEL_DIR = GENERATED / "models" / "constraint_bow_mlp"
ACTIVE_MODEL = GENERATED / "models" / "active_constraint_model.json"
EXCLUSIVE_PREFIXES = {"people_count", "day_count", "ticket_count", "taxi_cars", "metro_tickets"}


def tokenize(text: str, ngram_max: int = 1) -> list[str]:
    words = [t for t in re.findall(r"[A-Za-z0-9]+", text.lower()) if len(t) > 1]
    tokens = list(words)
    for n in range(2, max(1, ngram_max) + 1):
        tokens.extend("__".join(words[i : i + n]) for i in range(0, max(0, len(words) - n + 1)))
    return tokens


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def default_model_dir() -> Path:
    if ACTIVE_MODEL.exists():
        try:
            data = load_json(ACTIVE_MODEL)
            path = Path(data.get("model_dir", ""))
            if not path.is_absolute():
                path = LAB_ROOT.parent / path
            if path.exists():
                return path
        except (OSError, json.JSONDecodeError):
            pass
    return DEFAULT_MODEL_DIR


def vectorize(text: str, word_to_idx: dict[str, int], ngram_max: int = 1):
    import torch

    vec = torch.zeros(len(word_to_idx), dtype=torch.float32)
    for token in tokenize(text, ngram_max=ngram_max):
        idx = word_to_idx.get(token)
        if idx is not None:
            vec[idx] += 1.0
    return torch.log1p(vec) if vec.sum() > 0 else vec


def extract_rule_hints(text: str) -> list[dict[str, Any]]:
    text_norm = text.lower()
    hints: list[dict[str, Any]] = []
    people = re.search(r"\b(?:we are|group of|party of|for)\s+(\d+)\s+(?:people|persons|travelers|travellers)\b", text_norm)
    days = re.search(r"\b(?:for|spend|spending)\s+(\d+)\s+days?\b", text_norm)
    if people:
        hints.append({"label": f"people_count:{people.group(1)}", "source": "regex", "confidence": 1.0})
    if days:
        hints.append({"label": f"day_count:{days.group(1)}", "source": "regex", "confidence": 1.0})
    return hints


def filter_exclusive_predictions(
    rows: list[dict[str, Any]],
    threshold: float,
    semantic_threshold: float,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    best_by_prefix: dict[str, dict[str, Any]] = {}
    for row in rows:
        prefix = row["label"].split(":", 1)[0]
        if prefix not in EXCLUSIVE_PREFIXES:
            if row["probability"] < semantic_threshold:
                continue
            selected.append(row)
            continue
        if row["probability"] < threshold:
            continue
        old = best_by_prefix.get(prefix)
        if old is None or row["probability"] > old["probability"]:
            best_by_prefix[prefix] = row
    selected.extend(best_by_prefix.values())
    return sorted(selected, key=lambda row: row["probability"], reverse=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("text", nargs="?", default="")
    parser.add_argument("--query-json")
    parser.add_argument("--model-dir", default=str(default_model_dir()))
    parser.add_argument("--threshold", type=float, default=-1.0)
    parser.add_argument("--semantic-threshold", type=float, default=0.5)
    parser.add_argument("--top-k", type=int, default=20)
    args = parser.parse_args()

    try:
        import torch
        import torch.nn as nn
    except ImportError as exc:
        raise SystemExit("PyTorch is not installed. Use the conda torch environment.") from exc

    if args.query_json:
        data = load_json(Path(args.query_json))
        text = data.get("nature_language", "")
    else:
        text = args.text

    model_dir = Path(args.model_dir)
    words = load_json(model_dir / "word_vocab.json")
    labels = load_json(model_dir / "label_vocab.json")
    tokenizer_config_path = model_dir / "tokenizer_config.json"
    tokenizer_config = load_json(tokenizer_config_path) if tokenizer_config_path.exists() else {}
    ngram_max = int(tokenizer_config.get("ngram_max", 1))
    summary_path = model_dir / "training_summary.json"
    summary = load_json(summary_path) if summary_path.exists() else {}
    threshold = args.threshold if args.threshold >= 0 else float(summary.get("best", {}).get("threshold", 0.5))

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

    word_to_idx = {word: i for i, word in enumerate(words)}
    x = vectorize(text, word_to_idx, ngram_max=ngram_max).unsqueeze(0)
    with torch.no_grad():
        probs = torch.sigmoid(model(x))[0]
    ranked = sorted(
        (
            {"label": label, "probability": float(probs[i])}
            for i, label in enumerate(labels)
        ),
        key=lambda row: row["probability"],
        reverse=True,
    )
    print(
        json.dumps(
            {
                "text": text,
                "threshold": threshold,
                "semantic_threshold": args.semantic_threshold,
                "ngram_max": ngram_max,
                "rule_hints": extract_rule_hints(text),
                "predicted": filter_exclusive_predictions(ranked, threshold, max(threshold, args.semantic_threshold)),
                "top": ranked[: args.top_k],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
