# TPC Agent — Codex V10G

Constraint-driven travel planner for IJCAI 2026 Travel Planning Challenge.

## V10G Scores (2026-06-13)

| Split | N | Schema | MicEPR | C-LPR | FPR | Overall |
|---|---:|---:|---:|---:|---:|---:|
| `training_rand10` | 10 | 10/10 | 100.00 | 96.97 | 90.00 | **86.58** |
| `codex_rand30_s131` | 30 | 30/30 | 100.00 | 92.66 | 76.67 | **80.10** |
| `codex_rand10_s47` | 10 | 10/10 | 100.00 | 91.11 | 70.00 | **76.85** |
| `codex_v10_hardfail13` | 13 | 13/13 | 100.00 | 89.71 | 53.85 | **70.85** |
| `codex_rand10_s29` | 10 | 10/10 | 99.60 | 66.67 | 50.00 | **61.72** |
| `codex_rand10_s13` | 10 | 10/10 | 99.60 | 69.23 | 40.00 | **59.32** |

### Comparison

| Baseline | Split | Overall |
|---|---:|---:|
| V9 | `codex_rand30_s131` | 69.83 |
| V10G | `codex_rand30_s131` | **80.10** (+10.27) |
| V10C | `training_rand10` | 77.24 |
| V10G | `training_rand10` | **86.58** (+9.35) |

## V10G Changes

| File | Change |
|---|---|
| `src/constraints/nl_parser.py` | Treat named parks/museums as POI unless exact type alias match |
| `src/constraints/nl_parser.py` | Fix visit-clause boundary so `No. 1 Department Store` is not truncated |
| `src/constraints/nl_parser.py` | Stop `_clean_entity()` from deleting list items after `and` |
| `src/constraints/test_nl_parser.py` | 41 regression tests including Zhongshan Park, Exploration Capsule, Fly Over Shanghai / Changle Road |
| `src/planner/plan_builder.py` | Rebalance must-visit POIs away from arrival/final days onto middle full days |
| `src/planner/plan_builder.py` | Exact-first name matching; long fuzzy only when exact unavailable |
| `data/splits/codex_v10d_training_hard3.txt` | Targeted 3-query regression split |
| `ChinaTravel/chinatravel/evaluation/default_splits/codex_v10d_training_hard3.txt` | Same split for official evaluator |

## Unit Checks

```
src/constraints/test_nl_parser.py   41/41
py_compile nl_parser / plan_builder / test_nl_parser   Passed
codex_v10d_training_hard3   Overall 92.08, C-LPR 100, FPR 100
```

## Remaining Failure Families

| Split | Categories |
|---|---|
| `codex_rand30_s131` | innercity_transport, activity_time_window, attraction_name, hotel_distance, hotel_feature, innercity_transport_budget, restaurant_name |
| `codex_rand10_s13` | room_type, attraction_type, hotel_distance, hotel_name, innercity_transport |
| `codex_rand10_s29` | activity_time_window, food_type, innercity_transport_budget, intercity_transport, restaurant_name |
| `codex_rand10_s47` | hotel_name, innercity_transport_budget |

## Next Targets

1. `room_type`: twin/single-bed exact constraints in hotel ranking and accommodation payload
2. `hotel_name`: post-selection exact rescue when required hotel exists but fallback used
3. `restaurant_name`: schedule required restaurants into lunch/dinner windows, not breakfast
4. `innercity_transport_budget`: budget-aware local transport repair before final output
5. `activity_time_window`: targeted post-generation insertion for leave-after constraints

## Semantic Library

`semantic_library_lab/` — independent semantic constraint classifier:

- **Model**: `constraint_bow_mlp_hotel_budget_v3_bigram_cu13_lr0015_h512` (F1=0.70, 174 labels)
- **Active model**: `generated/models/active_constraint_model.json`
- **Failure corpus**: `generated/v9_semantic_alignment/` — hard-failure alignments for 7 splits
- **Scripts**: dataset preparation, training, prediction, alignment export

## Quick Start

```bash
conda activate dl_env
```

### Single query

```bash
python run_tpc.py --splits training --index <query_id> --lang en
```

### Batch evaluation

```bash
python run_tpc.py --splits <split_name> --lang en --official-results
cd ChinaTravel
python eval_tpc.py --splits <split_name> --method TPCAgent_TPCLLM_en --lang en
```

### Analysis

```bash
python scripts/eval_analyzer.py --splits <split_name> --method TPCAgent_TPCLLM_en --lang en --json
```

## Tests

```bash
python src/constraints/test_nl_parser.py        # 41/41
python src/constraints/test_hard_logic_parser.py
python src/skills/test_skills.py                 # 9/9
python src/constraints/test_constraints.py       # 5/5
python src/data_layer/test_data_layer.py         # 8/8
python src/candidates/test_candidates.py         # 3/3
python src/active/test_active.py                 # 3/3
python src/adapter/test_adapter.py               # 5/5
```

## Directory Structure

```
├── main.py / run_tpc.py         # Entry points
├── config.yaml                  # Global config
├── tpc_agent.py / tpc_llm.py    # Official Agent/LLM adapters
├── src/
│   ├── data_layer/              # Schema, WorldEnv client, cache
│   ├── constraints/             # NL parser, hard logic DSL, lexicons
│   ├── active/                  # Active constraint acquisition
│   ├── semantic/                # Cuisine/pace/preference grounding
│   ├── candidates/              # POI/hotel/restaurant candidate pools
│   ├── planner/                 # Multi-day allocation, rolling day planner
│   ├── optimizer/               # GA-TSP + 2-opt route optimization
│   ├── scheduler/               # Timetable + budget control
│   ├── repair/                  # Typed repair (FORMAT/TICKET/TRANSPORT/BUDGET/TIME/MEAL/MUST_VISIT)
│   ├── skills/                  # Travel planner skill library
│   ├── search/                  # Multi-candidate search, best-of-N
│   ├── verifier/                # Local checker, official verifier bridge
│   └── submission/              # Official format + schema validation
├── scripts/                     # Evaluation analysis tools
├── semantic_library_lab/        # Semantic classifier + failure corpus
├── ChinaTravel/                 # Official evaluation harness
│   └── results/                 # Evaluation results
└── data/
    ├── splits/                  # Evaluation split files
    └── training data/           # Query dataset (1000 queries)
```
