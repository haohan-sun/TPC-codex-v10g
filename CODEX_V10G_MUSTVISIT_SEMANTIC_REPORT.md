# Codex V10G Must-Visit + Name Grounding Report

Date: 2026-06-13

Scope: all planner changes were made only in `D:\IJCAI_TPC\recovery_lab\codex_worktrees\codex_rescue_v1`. `D:\IJCAI_TPC\demo1` was not modified.

## Why This Round

V10C improved fresh hard-logic generalization, but `training_rand10` dropped to 77.24 because several natural-language must-visit constraints were parsed or scheduled incorrectly. The main failure pattern was:

```text
named POI with a generic suffix -> treated as attraction type
multi-POI list with "No. 1" -> name truncated at "No."
must_visit POI assigned to Day 1 -> removed by late-arrival cross-city logic
short exact POI name -> fuzzy-matched many nearby POIs and exact one was skipped
```

## Code Changes

| File | Change |
| --- | --- |
| `src/constraints/nl_parser.py` | Treat named parks/museums as POI unless they exactly match a type alias. |
| `src/constraints/nl_parser.py` | Fix visit-clause boundary so `No. 1 Department Store` is not truncated. |
| `src/constraints/nl_parser.py` | Stop `_clean_entity()` from deleting list items after `and`. |
| `src/constraints/test_nl_parser.py` | Added three real regression tests for Zhongshan Park, Exploration Capsule, and Fly Over Shanghai/Changle Road. |
| `src/planner/plan_builder.py` | Rebalance must-visit POIs away from arrival/final days onto middle full days. |
| `src/planner/plan_builder.py` | Use exact-first name matching; long fuzzy only when exact match is unavailable. |
| `data/splits/codex_v10d_training_hard3.txt` | Added targeted 3-query regression split. |
| `ChinaTravel/chinatravel/evaluation/default_splits/codex_v10d_training_hard3.txt` | Same split for official evaluator. |

## Unit Checks

| Check | Result |
| --- | ---: |
| `py_compile nl_parser/plan_builder/test_nl_parser` | Passed |
| `src/constraints/test_nl_parser.py` | 41/41 passed |
| `codex_v10d_training_hard3` | Overall 92.08, C-LPR 100, FPR 100 |

## Official Evaluation

| Split | N | Schema | MicEPR | C-LPR | FPR | Overall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `training_rand10` | 10 | 10/10 | 100.00 | 96.97 | 90.00 | 86.58 |
| `codex_v10_hardfail13` | 13 | 13/13 | 100.00 | 89.71 | 53.85 | 70.85 |
| `codex_rand30_s131` | 30 | 30/30 | 100.00 | 92.66 | 76.67 | 80.10 |
| `codex_rand10_s13` | 10 | 10/10 | 99.60 | 69.23 | 40.00 | 59.32 |
| `codex_rand10_s29` | 10 | 10/10 | 99.60 | 66.67 | 50.00 | 61.72 |
| `codex_rand10_s47` | 10 | 10/10 | 100.00 | 91.11 | 70.00 | 76.85 |

## Comparison

| Baseline | Split | Overall | Note |
| --- | --- | ---: | --- |
| V9 | `codex_rand30_s131` | 69.83 | Previous stable random30 baseline |
| V10G | `codex_rand30_s131` | 80.10 | +10.27 overall, 23/30 all-pass |
| V10C | `codex_v10_hardfail13` | 70.86 | Previous hardfail13 best |
| V10G | `codex_v10_hardfail13` | 70.85 | Same level after training protection fixes |
| V10C | `training_rand10` | 77.24 | Must-visit regression present |
| V10G | `training_rand10` | 86.58 | +9.35 after parser/scheduler fixes |

## Remaining Failure Families

| Split | Main remaining categories |
| --- | --- |
| `codex_rand30_s131` | innercity_transport x2, activity_time_window x1, attraction_name x1, hotel_distance x1, hotel_feature x1, innercity_transport_budget x1, restaurant_name x1 |
| `codex_rand10_s13` | room_type x2, attraction_type x1, hotel_distance x1, hotel_name x1, innercity_transport x1, other x1 |
| `codex_rand10_s29` | activity_time_window x1, food_type x1, innercity_transport_budget x1, intercity_transport x1, restaurant_name x1 |
| `codex_rand10_s47` | hotel_name x3, innercity_transport_budget x1 |

## Next Low-Risk Targets

1. `room_type`: make twin/single-bed constraints exact in hotel ranking and selected accommodation payload.
2. `hotel_name`: add post-selection exact rescue when required hotel exists but accommodation later uses fallback.
3. `restaurant_name`: schedule required restaurants into lunch/dinner windows across multiple days, not breakfast.
4. `innercity_transport_budget`: budget-aware local transport repair before final output.
5. `activity_time_window`: targeted post-generation insertion for named restaurant/attraction leave-after constraints.

## Generated Failure Alignments

```text
D:\IJCAI_TPC\semantic_library_lab\generated\v9_semantic_alignment\codex_rand30_s131\CODEX_V10G_TPCLLM_en
D:\IJCAI_TPC\semantic_library_lab\generated\v9_semantic_alignment\codex_rand10_s13\CODEX_V10G_TPCLLM_en
D:\IJCAI_TPC\semantic_library_lab\generated\v9_semantic_alignment\codex_rand10_s29\CODEX_V10G_TPCLLM_en
D:\IJCAI_TPC\semantic_library_lab\generated\v9_semantic_alignment\codex_rand10_s47\CODEX_V10G_TPCLLM_en
D:\IJCAI_TPC\semantic_library_lab\generated\v9_semantic_alignment\codex_v10_hardfail13\CODEX_V10G_TPCLLM_en
```
