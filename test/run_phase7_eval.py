"""Phase 7: Generate TEMP results for fresh splits and run official eval."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tpc_agent import TPCAgent
from tpc_llm import TPCLLM

TRAINING_DIR = PROJECT_ROOT / "data" / "training data"
TEMP_METHOD = "TEMP_GENERALIZE_V1"
OUT_DIR = PROJECT_ROOT / "test" / "generalization_v1"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SPLITS = ["fresh_A10", "fresh_B10", "fresh_C10", "fresh_ALL30"]

agent = TPCAgent(env=None, backbone_llm=TPCLLM(), lang="en")

all_scores: dict[str, dict] = {}

for split_name in SPLITS:
    split_file = PROJECT_ROOT / "data" / "splits" / f"{split_name}.txt"
    ids = [line.strip() for line in split_file.read_text().splitlines() if line.strip()]
    print(f"\n{'='*60}")
    print(f"Split: {split_name} ({len(ids)} queries)")
    print(f"{'='*60}")

    # Generate
    results_dir = PROJECT_ROOT / "ChinaTravel" / "results" / f"{TEMP_METHOD}_{split_name}_en"
    results_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.monotonic()
    succ = 0
    for i, uid in enumerate(ids):
        query_path = TRAINING_DIR / f"{uid}.json"
        query = json.loads(query_path.read_text(encoding="utf-8"))
        try:
            ok, plan = agent.run(query, prob_idx=uid, oralce_translation=False)
        except Exception as exc:
            ok, plan = False, {"error": str(exc), "itinerary": []}
        if ok:
            succ += 1
        out_path = results_dir / f"{uid}.json"
        out_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  [{i+1}/{len(ids)}] {uid} {'OK' if ok else 'FAIL'}")

    elapsed = time.monotonic() - t0
    print(f"  Generated: {succ}/{len(ids)} in {elapsed:.1f}s")

    # Eval
    print(f"  Running eval...")
    result = subprocess.run(
        [sys.executable, "eval_tpc.py", "--splits", split_name, "--method", f"{TEMP_METHOD}_{split_name}", "--lang", "en"],
        cwd=str(PROJECT_ROOT / "ChinaTravel"),
        capture_output=True, text=True,
    )
    # Parse scores
    score_data = {"split": split_name, "n": len(ids), "succ": succ}
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("Mic.EPR"):
            score_data["MicEPR"] = float(line.split()[-1])
        elif line.startswith("C-LPR"):
            score_data["C-LPR"] = float(line.split()[-1])
        elif line.startswith("FPR"):
            score_data["FPR"] = float(line.split()[-1])
        elif line.startswith("Overall Score"):
            score_data["Overall"] = float(line.split()[-1])
        elif "schema_pass" in line.lower():
            score_data["schema_pass"] = line.strip()
        elif "commonsense_pass" in line.lower():
            score_data["commonsense_pass"] = line.strip()
        elif "hard_pass" in line.lower():
            score_data["hard_pass"] = line.strip()
        elif "all_pass" in line.lower():
            score_data["all_pass"] = line.strip()
        elif line.startswith("[") and "]" in line:
            # [0.7625     0.98677994 0.75555556]
            parts = line.strip("[]").split()
            if len(parts) == 3:
                score_data["DAV"] = float(parts[0])
                score_data["ATT"] = float(parts[1])
                score_data["DDR"] = float(parts[2])
    all_scores[split_name] = score_data
    print(f"  Overall: {score_data.get('Overall', '?')}")

# Write scores.md and scores.csv
md = OUT_DIR / "scores.md"
csv = OUT_DIR / "scores.csv"
lines_md = [
    "# TEMP_GENERALIZE_V1 — Fresh Random 30 Scores",
    "",
    "| Split | N | Succ | Schema | Commonsense | Hard | All | MicEPR | C-LPR | FPR | DAV | ATT | DDR | Overall |",
    "|-------|---|------|--------|-------------|------|-----|--------|-------|-----|-----|-----|-----|---------|",
]
lines_csv = ["Split,N,Succ,Schema,Commonsense,Hard,All,MicEPR,C-LPR,FPR,DAV,ATT,DDR,Overall"]
for name in SPLITS + ["training_rand10"]:
    s = all_scores.get(name, {})
    if name == "training_rand10":
        s = {"split": "training_rand10", "n": 10, "Overall": 97.524,
             "MicEPR": 100, "C-LPR": 100, "FPR": 100, "DAV": 76.25, "ATT": 98.68, "DDR": 75.56,
             "schema_pass": "10/10", "commonsense_pass": "7/10", "hard_pass": "7/10", "all_pass": "5/10", "succ": 10}
    lines_md.append(
        f"| {s.get('split','?')} | {s.get('n','?')} | {s.get('succ','?')} | "
        f"{s.get('schema_pass','?')} | {s.get('commonsense_pass','?')} | "
        f"{s.get('hard_pass','?')} | {s.get('all_pass','?')} | "
        f"{s.get('MicEPR','?')} | {s.get('C-LPR','?')} | {s.get('FPR','?')} | "
        f"{s.get('DAV','?')} | {s.get('ATT','?')} | {s.get('DDR','?')} | "
        f"**{s.get('Overall','?')}** |"
    )
    lines_csv.append(
        f"{name},{s.get('n','')},{s.get('succ','')},{s.get('schema_pass','')},"
        f"{s.get('commonsense_pass','')},{s.get('hard_pass','')},{s.get('all_pass','')},"
        f"{s.get('MicEPR','')},{s.get('C-LPR','')},{s.get('FPR','')},"
        f"{s.get('DAV','')},{s.get('ATT','')},{s.get('DDR','')},{s.get('Overall','')}"
    )

md.write_text("\n".join(lines_md), encoding="utf-8")
csv.write_text("\n".join(lines_csv), encoding="utf-8")
print(f"\nReports: {md}, {csv}")
print("Phase 7 complete.")
