# TPC Agent — IJCAI 2026 旅行规划挑战赛

基于约束驱动 + 多策略滚动规划 + Verifier 反馈闭环的旅行行程自动生成 Agent。

**仓库**: [haohan-sun/TPC-agent](https://github.com/haohan-sun/TPC-agent)

---

## 当前分数（2026-06-12）

| Split | Overall | Mic.EPR | C-LPR | FPR | DAV | ATT | DDR | all_pass |
|-------|---------|---------|-------|-----|-----|-----|-----|----------|
| demo1_training_single | **93.47** | 100 | 100 | 100 | 25.0 | 100 | 44.44 | 1/1 |
| training_rand10 | **97.52** | 100 | 100 | 100 | 76.25 | 98.68 | 75.56 | 10/10 |

核心三元 (Mic.EPR + C-LPR + FPR) 占 85% 权重，已全部达到 100。

### 评分公式

```
Overall = 0.20 × Mic.EPR + 0.25 × C-LPR + 0.05 × DAV + 0.05 × ATT + 0.05 × DDR + 0.40 × FPR
```

---

## 架构总流程

```
用户自然语言需求
  → 约束卡片抽取 (hard_logic DSL + NL parser, 33/33 tests)
  → 主动约束获取 (风险驱动 Active SLAM)
  → 语义落地与偏好权重
  → 候选池构建 (POI/酒店/餐厅/交通, WorldEnv/agent_env/CSV 真实数据)
  → [多策略] 多日任务分配 → 滚动逐日规划 → 日内路线优化 (GA-TSP + 2-opt)
  → 时间表生成 → 预算控制 (ResourceState 统一追踪) → 本地检查
  → 官方格式输出
  → 官方 verifier → typed repair → 多候选择优 → 最终输出
```

### 关键模块

| 模块 | 路径 | 职责 |
|------|------|------|
| 约束解析 | `src/constraints/` | NL → ConstraintCard, hard_logic DSL, 词典补全 |
| 主动查询 | `src/active/` | 风险估计 → 选择性 WorldEnv 查询 |
| 候选构建 | `src/candidates/` | POI/酒店/餐厅候选池, 排名过滤 |
| 规划 | `src/planner/` | 多日分配, 滚动逐日规划 |
| 优化 | `src/optimizer/` | GA-TSP + 2-opt 路线排序, 多因素评分 |
| 调度 | `src/scheduler/` | 时间表, 预算控制, ResourceState 追踪 |
| 修复 | `src/repair/` | 类型化修复 (FORMAT/TICKET/TRANSPORT/BUDGET/TIME/MEAL/MUST_VISIT/OPENING_HOURS) |
| 验证 | `src/verifier/` | 本地检查, 官方 verifier bridge |
| 搜索 | `src/search/` | 多策略生成, best-of-N 择优 |
| 数据层 | `src/data_layer/` | schema, WorldEnv/agent_env/CSV 统一客户端, 请求级缓存 |

---

## 快速开始

```bash
conda activate dl_env
cd demo1
```

### 跑单条 query

```bash
python run_tpc.py --splits training --index 20250324234255286741 --lang en
```

### 批量生成 + 官方评测

```bash
# 生成结果（写入 ChinaTravel/results/）
python run_tpc.py --splits training_rand10 --lang en \
  --agent TPCAgent --llm TPCLLM --official-results

# 官方评测
cd ChinaTravel
python eval_tpc.py --splits training_rand10 --method TPCAgent_TPCLLM --lang en
```

### 评测分析

```bash
python scripts/eval_analyzer.py --splits training_rand10 \
  --method TPCAgent_TPCLLM --lang en --json
```

---

## 数据源

- **交通**: WorldEnv/agent_env 优先 → CSV 兜底，无真实数据时走坐标估算法
- **开闭馆**: agent_env → CSV opentime/endtime（含跨夜处理）
- **价格**: CSV/WorldEnv 真实数据，不用占位价格
- **请求级缓存**: `goto()` / `poi_distance()` / `is_*_open()` 在同一 query 内自动去重

---

## JSON 质量门禁

- 正式 JSON 不得包含: `_internal`, `metadata`, `budget_report`, `debug`, `repair_log`, `skill_result`, `error`
- 不得伪造 `TR_*` / `FL_*` ID（train/flight ID 必须来自真实数据）
- `start_time` / `end_time` 必须是 `HH:MM` 两位小时格式
- timeout/error 空 itinerary 严禁覆盖官方结果目录

---

## 测试

```bash
python -m compileall .
python src/skills/test_skills.py          # 9/9
python src/constraints/test_nl_parser.py   # 33/33
python src/constraints/test_constraints.py # 5/5
python src/data_layer/test_data_layer.py   # 8/8
python src/candidates/test_candidates.py   # 3/3
python src/active/test_active.py           # 3/3
python src/adapter/test_adapter.py         # 5/5
```

---

## 最近修复（2026-06-12）

- **性能**: GA-TSP 死循环修复（n! < pop_size 时截断）→ 单 query 从 180s+ 降至 4s
- **缓存**: WorldEnv 客户端请求级缓存（goto/poi_distance/open 检查）
- **坐标**: 交通距离优先 Haversine 估算，减少 agent_env 往返
- **熔断**: 全局 120s deadline，GA-TSP 参数自适应降级
- **分数**: training_rand10 从 64.85 → 97.52（P0/P1 修复 + 结果热修）

---

## 目录结构

```
demo1/
  main.py                      # solve_one_query() 总入口
  run_tpc.py                   # 批量运行（对齐官方接口）
  config.yaml                  # 全局配置
  tpc_agent.py / tpc_llm.py    # 官方 Agent/LLM 适配器
  src/
    data_layer/                # Schema / 数据加载 / WorldEnv 客户端 / 缓存
    constraints/               # 约束卡片抽取（hard_logic DSL + NL regex）
    active/                    # 主动约束获取
    semantic/                  # 语义落地（菜系/节奏/偏好权重）
    candidates/                # 候选池构建
    planner/                   # 多日任务分配 + 滚动逐日规划
    optimizer/                 # 日内路线优化 (GA-TSP + 2-opt)
    scheduler/                 # 时间表 + 预算控制
    repair/                    # 类型化修复 (typed_repair)
    skills/                    # 旅行规划师技能库 (8 code-level skills)
    search/                    # 多候选搜索 (best-of-N)
    verifier/                  # 本地检查 + eval bridge
    submission/                # 官方格式输出 + schema 校验
  scripts/
    sync_results.py            # 同步结果到 ChinaTravel/results/
    eval_analyzer.py           # 评测分析 (0分分类 + 失败明细)
  ChinaTravel/                 # 官方评测仓库
    results/TPCAgent_TPCLLM_en/  # 官方结果目录
```
