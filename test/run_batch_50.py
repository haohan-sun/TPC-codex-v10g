"""批量跑 50 条 query，记录每条耗时，写入 test/ 目录。"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tpc_agent import TPCAgent
from tpc_llm import TPCLLM

SPLIT_FILE = PROJECT_ROOT / "test" / "test_50.txt"
OUTPUT_DIR = PROJECT_ROOT / "test" / "results"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TRAINING_DIR = PROJECT_ROOT / "data" / "training data"
TIMEOUT = 300

# 加载 query ID 列表
ids = [line.strip() for line in SPLIT_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
print(f"加载 {len(ids)} 条 query")

agent = TPCAgent(env=None, backbone_llm=TPCLLM(), lang="en")

results = []
succ_count = 0
total_time = 0.0

for i, uid in enumerate(ids):
    query_path = TRAINING_DIR / f"{uid}.json"
    if not query_path.exists():
        print(f"[{i+1}/{len(ids)}] {uid} — MISSING")
        continue

    query = json.loads(query_path.read_text(encoding="utf-8"))
    print(f"[{i+1}/{len(ids)}] {uid} ...", end=" ", flush=True)

    t0 = time.monotonic()
    try:
        succ, plan = agent.run(query, prob_idx=uid, oralce_translation=False)
    except Exception as exc:
        succ, plan = False, {"error": str(exc), "itinerary": []}
    elapsed = time.monotonic() - t0

    total_time += elapsed
    if succ:
        succ_count += 1

    # 保存结果
    out_path = OUTPUT_DIR / f"{uid}.json"
    out_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    itin_len = len(plan.get("itinerary", []))
    status = "OK" if succ else "FAIL"
    print(f"{elapsed:.1f}s, itinerary={itin_len}, {status}")

    results.append({
        "uid": uid,
        "elapsed_sec": round(elapsed, 2),
        "succ": succ,
        "itinerary_len": itin_len,
    })

# 保存 timing 记录
timing_path = PROJECT_ROOT / "test" / "timing.json"
timing_path.write_text(json.dumps({
    "total_queries": len(ids),
    "succ_count": succ_count,
    "total_sec": round(total_time, 1),
    "avg_sec": round(total_time / max(len(ids), 1), 2),
    "results": results,
}, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"\n{'='*50}")
print(f"完成: {succ_count}/{len(ids)} 成功")
print(f"总耗时: {total_time:.1f}s")
print(f"平均: {total_time/max(len(ids),1):.1f}s/query")
print(f"结果: {OUTPUT_DIR}")
print(f"时序: {timing_path}")
