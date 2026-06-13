"""批量跑1000条query + 官方评测 + 输出CSV。最快模式：单policy，8进程并行。"""
import os, sys, json, csv, time, traceback
from pathlib import Path
from multiprocessing import Pool, cpu_count

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

# 强制单 policy 快速模式
os.environ['TPC_FAST_MODE'] = '1'

try:
    from func_timeout import func_timeout, FunctionTimedOut
except ImportError:
    FunctionTimedOut = TimeoutError

    def func_timeout(timeout, func, args=None, kwargs=None):
        return func(*(args or ()), **(kwargs or {}))


QUERY_TIMEOUT_SEC = int(os.environ.get('TPC_BATCH_QUERY_TIMEOUT', '90'))

def run_one_query(uid: str) -> dict:
    """单 query 生成 + 校验。返回结果字典。"""
    t0 = time.time()
    result = {
        'query_id': uid,
        'status': 'unknown',
        'overall': None, 'mic_epr': None, 'c_lpr': None, 'fpr': None,
        'dav': None, 'att': None, 'ddr': None,
        'days': 0, 'activities': 0,
        'error': '', 'time_sec': 0,
    }
    try:
        # 加载 query
        from src.data_layer.loaders import query_from_dict
        qpath = BASE / 'data/training data' / f'{uid}.json'
        with open(qpath, encoding='utf-8') as f:
            raw = json.load(f)
        raw['uid'] = uid
        query = query_from_dict(raw)

        # 生成 plan
        from main import solve_one_query
        from src.adapter.plan_formatter import format_official_plan
        try:
            pipeline_result = func_timeout(QUERY_TIMEOUT_SEC, solve_one_query, args=(query,))
        except FunctionTimedOut:
            result['error'] = f'timeout>{QUERY_TIMEOUT_SEC}s'
            result['status'] = 'timeout'
            result['time_sec'] = round(time.time() - t0, 1)
            return result
        plan = format_official_plan(raw, pipeline_result, elapsed_sec=time.time() - t0)

        # 校验基本结构
        itinerary = plan.get('itinerary', [])
        if not itinerary:
            result['error'] = 'empty itinerary'
            result['status'] = 'empty'
            result['time_sec'] = time.time() - t0
            return result

        days = len(itinerary)
        acts = sum(len(d.get('activities', [])) for d in itinerary)

        # 写入 TEMP 结果目录
        temp_method = 'TEMP_BATCH_1000'
        temp_dir = BASE / 'ChinaTravel/results' / f'{temp_method}_en'
        temp_dir.mkdir(parents=True, exist_ok=True)
        clean = {k: v for k, v in plan.items()
                 if not k.startswith('_') and k not in ('error', 'score', 'metadata', 'budget_report')}
        with open(temp_dir / f'{uid}.json', 'w', encoding='utf-8') as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)

        # 创建临时 split 并跑官方 eval（单个 query）
        split_file = BASE / 'ChinaTravel/chinatravel/evaluation/default_splits' / f'_temp_{uid}.txt'
        split_file.write_text(uid + '\n', encoding='utf-8')

        # 拷贝 query 数据到 eval 目录
        eval_data_dir = BASE / 'ChinaTravel/chinatravel/data/en' / f'_temp_{uid}'
        eval_data_dir.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy(qpath, eval_data_dir / f'{uid}.json')

        # 跑 eval_tpc.py（子进程，避免污染当前环境）
        import subprocess
        ct = BASE / 'ChinaTravel'
        r = subprocess.run(
            [sys.executable, str(ct / 'eval_tpc.py'),
             '--splits', f'_temp_{uid}',
             '--method', temp_method,
             '--lang', 'en'],
            cwd=str(ct), capture_output=True, text=True, timeout=120
        )
        output = r.stdout + r.stderr

        # 解析分数
        for line in output.split('\n'):
            line = line.strip()
            if 'Overall Score:' in line:
                result['overall'] = float(line.split(':')[-1].strip())
            elif 'Mic.EPR' in line and 'Mac.EPR' not in line:
                try: result['mic_epr'] = float(line.split()[-1])
                except: pass
            elif 'C-LPR:' in line:
                try: result['c_lpr'] = float(line.split(':')[-1].strip())
                except: pass
            elif 'FPR:' in line:
                try: result['fpr'] = float(line.split(':')[-1].strip())
                except: pass

        # 从 eval 输出提取 DAV/ATT/DDR
        for line in output.split('\n'):
            if line.startswith('[') and 'np.float64' not in line:
                parts = line.strip('[]').split()
                if len(parts) >= 3:
                    try:
                        result['dav'] = float(parts[0]) * 100
                        result['att'] = float(parts[1]) * 100
                        result['ddr'] = float(parts[2]) * 100
                    except: pass

        result['days'] = days
        result['activities'] = acts
        result['status'] = 'ok'
        result['time_sec'] = round(time.time() - t0, 1)

        # 清理临时文件
        try:
            split_file.unlink(missing_ok=True)
            shutil.rmtree(eval_data_dir)
        except: pass

    except Exception as e:
        result['error'] = f'{type(e).__name__}: {str(e)[:200]}'
        result['status'] = 'error'
        result['time_sec'] = round(time.time() - t0, 1)

    return result


def main():
    # 加载 query 列表
    with open(BASE / 'data/splits/training_full.txt', encoding='utf-8') as f:
        all_ids = f.read().strip().split()
    print(f'Total queries: {len(all_ids)}')

    # 检查官方稳定结果，只用于避开已覆盖的 baseline；候选始终写 TEMP_BATCH_1000_en。
    existing = set()
    results_dir = BASE / 'ChinaTravel/results/TPCAgent_TPCLLM_en'
    if results_dir.exists():
        existing = {f.stem for f in results_dir.glob('*.json')}
    todo = [uid for uid in all_ids if uid not in existing]
    print(f'Already done: {len(existing)}, Need to run: {len(todo)}')

    if not todo:
        todo = all_ids  # 重跑全部

    # 多进程并行
    n_workers = min(8, cpu_count(), len(todo))
    print(f'Workers: {n_workers}')
    print(f'Estimated: ~{len(todo)*2/n_workers/60:.0f} min')

    results = []
    t_start = time.time()
    completed = 0
    errors = 0

    with Pool(n_workers) as pool:
        for i, r in enumerate(pool.imap_unordered(run_one_query, todo)):
            results.append(r)
            if r['status'] == 'ok':
                completed += 1
            else:
                errors += 1
            elapsed = time.time() - t_start
            rate = (i + 1) / max(elapsed, 1)
            eta = (len(todo) - i - 1) / max(rate, 0.001)
            if (i + 1) % 50 == 0 or i < 5:
                print(f'[{i+1}/{len(todo)}] {elapsed:.0f}s OK={completed} ERR={errors} rate={rate:.1f}/s ETA={eta:.0f}s')

    total_time = time.time() - t_start
    print(f'\nDone: {completed} ok, {errors} errors in {total_time:.0f}s ({total_time/60:.1f}min)')

    # 统计
    scores = [r['overall'] for r in results if r['overall'] is not None]
    if scores:
        print(f'\n=== Score Statistics ===')
        print(f'  Count: {len(scores)}')
        print(f'  Mean:  {sum(scores)/len(scores):.2f}')
        print(f'  Min:   {min(scores):.2f}')
        print(f'  Max:   {max(scores):.2f}')
        print(f'  >=90:  {sum(1 for s in scores if s >= 90)}')
        print(f'  >=80:  {sum(1 for s in scores if s >= 80)}')
        print(f'  >=60:  {sum(1 for s in scores if s >= 60)}')
        print(f'  <60:   {sum(1 for s in scores if s < 60)}')

    # 写 CSV
    csv_path = BASE / 'data/outputs/batch_1000_results.csv'
    fieldnames = ['query_id', 'status', 'overall', 'mic_epr', 'c_lpr', 'fpr',
                  'dav', 'att', 'ddr', 'days', 'activities', 'time_sec', 'error']
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in sorted(results, key=lambda x: x['query_id']):
            writer.writerow(r)

    print(f'\nCSV written: {csv_path}')
    print(f'Rows: {len(results)}')


if __name__ == '__main__':
    main()
