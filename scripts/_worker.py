"""Worker: generate plans for a chunk of queries."""
import sys, json, os, time
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
os.environ['TPC_FAST_MODE'] = '1'

chunk_id = int(sys.argv[1])
chunk_file = BASE / f'data/splits/_chunk_{chunk_id}.txt'

with open(chunk_file, encoding='utf-8') as f:
    ids = f.read().strip().split()

from src.data_layer.loaders import query_from_dict
from src.adapter.plan_formatter import format_official_plan
from main import solve_one_query

temp_dir = BASE / 'ChinaTravel/results/TEMP_BATCH_1000_en'
temp_dir.mkdir(parents=True, exist_ok=True)

ok = 0
err = 0
t0 = time.time()

for i, uid in enumerate(ids):
    try:
        qpath = BASE / 'data/training data' / f'{uid}.json'
        with open(qpath, encoding='utf-8') as f:
            raw = json.load(f)
        raw['uid'] = uid
        query = query_from_dict(raw)
        plan = format_official_plan(raw, solve_one_query(query), elapsed_sec=time.time() - t0)
        clean = {k: v for k, v in plan.items()
                 if not k.startswith('_') and k not in ('error', 'score', 'metadata', 'budget_report')}
        with open(temp_dir / f'{uid}.json', 'w', encoding='utf-8') as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
        ok += 1
    except Exception as e:
        err += 1

    if (i + 1) % 20 == 0:
        print(f'[W{chunk_id}] {i+1}/{len(ids)} OK={ok} ERR={err} {time.time()-t0:.0f}s')

elapsed = time.time() - t0
print(f'[W{chunk_id}] DONE: {ok}/{len(ids)} OK in {elapsed:.0f}s')
with open(BASE / f'data/outputs/_chunk_{chunk_id}_done.txt', 'w') as f:
    f.write(f'DONE {ok}/{len(ids)} OK {err} ERR {elapsed:.0f}s')
