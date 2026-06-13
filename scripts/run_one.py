"""单query全流程：生成 + 评分。

用法:
    python scripts/run_one.py <uid>
"""
import sys, json, time, subprocess, shutil, os
from pathlib import Path

B = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(B))

uid = sys.argv[1] if len(sys.argv) > 1 else '20250322153344702263'
print(f'Query: {uid}')

qpath = B / 'data/training data' / f'{uid}.json'
raw = json.loads(qpath.read_text(encoding='utf-8'))
raw['uid'] = uid
print(f'  {raw.get("nature_language","")[:100]}')

from src.data_layer.loaders import query_from_dict
from src.adapter.plan_formatter import format_official_plan
from main import solve_one_query

t0 = time.time()
pipeline_result = solve_one_query(query_from_dict(raw))
gen_t = time.time() - t0

# Normalize itinerary
clean = format_official_plan(raw, pipeline_result, elapsed_sec=gen_t)
days = [d for d in clean.get('itinerary', []) if isinstance(d, dict)]
acts = sum(len(d.get('activities', [])) for d in days)
print(f'Plan: {len(days)}d {acts}acts ({gen_t:.1f}s)')

# Write clean result. Never touch the protected official TPCAgent_TPCLLM_en dir.
m = os.environ.get('TPC_TEMP_METHOD', 'TEMP_DEMO')
if m.endswith('_en'):
    result_method_dir = m
    eval_method = m[:-3]
else:
    result_method_dir = f'{m}_en'
    eval_method = m
clean['itinerary'] = days
result_dir = B / 'ChinaTravel/results' / result_method_dir
result_dir.mkdir(parents=True, exist_ok=True)
(result_dir / f'{uid}.json').write_text(
    json.dumps(clean, ensure_ascii=False, indent=2), encoding='utf-8')

# Setup eval
sn = f'_demo_{uid[:6]}'
split_file = B / 'ChinaTravel/chinatravel/evaluation/default_splits' / f'{sn}.txt'
split_file.write_text(uid + '\n', encoding='utf-8')
ed = B / 'ChinaTravel/chinatravel/data/en' / sn
ed.mkdir(parents=True, exist_ok=True)
shutil.copy(qpath, ed / f'{uid}.json')

# Run eval
ct = B / 'ChinaTravel'
r = subprocess.run(
    [sys.executable, str(ct / 'eval_tpc.py'), '--splits', sn, '--method', eval_method, '--lang', 'en'],
    cwd=str(ct), capture_output=True, text=True, timeout=120
)
for line in (r.stdout + r.stderr).split('\n'):
    if line.strip() and any(k in line for k in ['Overall Score', 'Mic.EPR', 'C-LPR', 'FPR', 'DAV', 'ATT', 'DDR']):
        print(line.strip())

# Cleanup
split_file.unlink(missing_ok=True)
shutil.rmtree(ed, ignore_errors=True)
print(f'Total: {time.time() - t0:.1f}s')
