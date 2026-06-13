"""生成一批新 query，默认写入 TEMP 目录。

官方稳定目录受 watchdog 保护；候选结果先写 TEMP_GEN_en，评测优于当前
baseline 后再人工提升。
"""
import sys, json, time, os, argparse
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
os.environ['TPC_FAST_MODE'] = '1'

parser = argparse.ArgumentParser(description='Generate candidate plans for a batch of training queries.')
parser.add_argument('--limit', type=int, default=30)
parser.add_argument('--method', default='TEMP_GEN', help='Result method name, _en suffix optional.')
parser.add_argument('--official', action='store_true', help='Explicitly write TPCAgent_TPCLLM_en.')
args = parser.parse_args()

if args.official:
    method_dir = 'TPCAgent_TPCLLM_en'
else:
    method_dir = args.method if args.method.endswith('_en') else f'{args.method}_en'

official_existing = {
    f.stem for f in (BASE / 'ChinaTravel/results/TPCAgent_TPCLLM_en').glob('*.json')
}
target_existing = {
    f.stem for f in (BASE / 'ChinaTravel/results' / method_dir).glob('*.json')
}
existing = official_existing | target_existing
with open(BASE / 'data/splits/training_full.txt', encoding='utf-8') as f:
    all_ids = f.read().strip().split()
todo = [uid for uid in all_ids if uid not in existing][:args.limit]

print(f'Running {len(todo)} queries -> ChinaTravel/results/{method_dir}')
sys.stdout.flush()

from src.data_layer.loaders import query_from_dict
from src.adapter.plan_formatter import format_official_plan
from main import solve_one_query

results_dir = BASE / 'ChinaTravel/results' / method_dir
results_dir.mkdir(parents=True, exist_ok=True)
t0 = time.time()
ok = err = 0

for i, uid in enumerate(todo):
    tq = time.time()
    try:
        qpath = BASE / 'data/training data' / f'{uid}.json'
        with open(qpath, encoding='utf-8') as f:
            raw = json.load(f)
        raw['uid'] = uid
        plan = format_official_plan(raw, solve_one_query(query_from_dict(raw)), elapsed_sec=time.time() - tq)
        it = plan.get('itinerary', [])
        clean = {k: v for k, v in plan.items() if not k.startswith('_') and k not in ('error','score','metadata','budget_report')}
        with open(results_dir / f'{uid}.json', 'w', encoding='utf-8') as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
        ok += 1
        elapsed = time.time() - t0
        print(f'[{i+1:2d}] {uid} OK {len(it)}d ({time.time()-tq:.1f}s) total={elapsed:.0f}s')
        sys.stdout.flush()
    except Exception as e:
        err += 1
        print(f'[{i+1:2d}] {uid} ERR {type(e).__name__}: {str(e)[:150]}')
        sys.stdout.flush()

elapsed = time.time() - t0
print(f'\n{ok}/{len(todo)} OK, {err} errors in {elapsed:.0f}s')
print(f'Files now: {len(list(results_dir.glob("*.json")))}')
