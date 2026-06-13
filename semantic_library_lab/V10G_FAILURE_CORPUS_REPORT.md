# V10G Semantic Failure Corpus Report

Date: 2026-06-13

Scope: semantic assets only under `D:\IJCAI_TPC\semantic_library_lab`. No `demo1` files were modified.

## What Was Added

V10G evaluation exported per-query hard-failure alignment files for:

```text
codex_rand30_s131
codex_rand10_s13
codex_rand10_s29
codex_rand10_s47
codex_v10_hardfail13
training_rand10
codex_v10d_training_hard3
```

Each output directory contains:

```text
semantic_hard_alignment.csv
semantic_hard_alignment.jsonl
```

These files connect:

```text
natural language query
  -> semantic model predicted labels
  -> official hard failure categories
  -> pass/fail status
```

## Current Signal

| Split | Hard pass | Main semantic misses |
| --- | ---: | --- |
| `codex_rand30_s131` | 23/30 | transport exact rules, time windows, hotel distance/feature, restaurant name |
| `codex_rand10_s13` | 4/10 | room type, hotel name/distance, attraction type, innercity transport |
| `codex_rand10_s29` | 5/10 | time window, food type, transport budget, intercity transport, restaurant name |
| `codex_rand10_s47` | 7/10 | hotel name, transport budget |

## Training Use

Do not train directly on planner pass/fail as truth. Use the corpus as hard-negative and missing-label mining:

1. For each failed query, compare `selected_labels` against `failure_categories`.
2. Add missing positive labels only when the natural language explicitly states them.
3. Add hard negatives when the model predicts a family absent from hard logic or contradicted by the query.
4. Keep planner-specific failures separate from semantic failures:
   - semantic: label missing or wrong family
   - planner: label correct but plan violates it

## Next Semantic Training Batch

Recommended new labels/templates:

| Family | Need |
| --- | --- |
| `room_type` | single-bed vs twin-bed exact phrasing and negated phrasing |
| `hotel_names` | exact hotel list extraction, punctuation/spacing variants |
| `restaurant_names` | multi-restaurant OR lists and required restaurant scheduling hints |
| `distance_taxi_rule` | "if distance exceeds X, take taxi" |
| `innercity_transport_budget` | local transportation budget phrases |
| `activity_time_window` | "leave X no earlier than HH:MM" |
| `food_type` | "try one of following restaurant types" aliases |

## Recommended Command Chain

```powershell
cd D:\IJCAI_TPC\semantic_library_lab
& 'C:\Users\Lenovo\miniconda3\envs\dl_env\python.exe' scripts\prepare_ml_dataset.py --min-label-count 2 --valid-ratio 0.15 --seed 20260613
& 'C:\Users\Lenovo\miniconda3\envs\tpc_torch_cu13\python.exe' scripts\train_constraint_classifier.py --dataset-dir generated\ml_dataset --model-name constraint_bow_mlp_v10g_failure_mined_cu13 --epochs 120 --min-epochs 40 --patience 16 --lr 0.0015 --hidden 512 --ngram-max 2 --threshold -1 --device cuda --seed 20260613
```

Only promote a new model to `generated\models\active_constraint_model.json` if it beats the current V3 model on both validation F1 and V10G failure-family hit rate.
