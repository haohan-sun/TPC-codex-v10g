# Codex Validation Scores (20260612_155256)

Fresh Codex-run validation. Claude test/results were not used.

- Method: `CODEX_VALIDATION_20260612_155256_en`
- Sample: 30 deterministic random training queries, excluding Claude test_50 and training_rand10.
- Successful fresh generations: `30/30`

| Split | N | Schema | Commonsense | Hard | All | MicEPR | C-LPR | FPR | DAV | ATT | DDR | Overall |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CODEX_VALIDATION_20260612_155256_A10 | 10 | 10/10 | 0/10 | 5/10 | 0/10 | 83.20 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 16.64 |
| CODEX_VALIDATION_20260612_155256_B10 | 10 | 10/10 | 0/10 | 4/10 | 0/10 | 83.60 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 16.72 |
| CODEX_VALIDATION_20260612_155256_C10 | 10 | 10/10 | 0/10 | 5/10 | 0/10 | 85.20 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 17.04 |
| CODEX_VALIDATION_20260612_155256_ALL30 | 30 | 30/30 | 0/30 | 14/30 | 0/30 | 84.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 16.80 |

## Main Finding

All 30 fresh generations produced non-empty itineraries, but none passed the full official gate. The blocker is not schema; it is commonsense plus hard-logic satisfaction on random unseen training queries.

## Top Failure Types

- `CODEX_VALIDATION_20260612_155256_A10`: Incorrect Information of Inner-City Transporton on price, distance, and duration: 10; Unavailable Inner-City Transport: 9; Inccorrect cost information of Inner-City Transport: 9; Invalid Transport information across positions: 4; Visiting attraction in their closed time: 2; Visiting Restruants in their closed time: 2
- `CODEX_VALIDATION_20260612_155256_B10`: Incorrect Information of Inner-City Transporton on price, distance, and duration: 10; Unavailable Inner-City Transport: 9; Inccorrect cost information of Inner-City Transport: 9; Invalid Transport information across positions: 4; Does not follow Chronological Order: 3; Unavailable Restruants: 1
- `CODEX_VALIDATION_20260612_155256_C10`: Unavailable Inner-City Transport: 10; Incorrect Information of Inner-City Transporton on price, distance, and duration: 10; Inccorrect cost information of Inner-City Transport: 10; Visiting Restruants in their closed time: 3; Visiting attraction in their closed time: 2; Does not follow Chronological Order: 1
- `CODEX_VALIDATION_20260612_155256_ALL30`: Incorrect Information of Inner-City Transporton on price, distance, and duration: 30; Unavailable Inner-City Transport: 28; Inccorrect cost information of Inner-City Transport: 28; Invalid Transport information across positions: 9; Visiting Restruants in their closed time: 6; Does not follow Chronological Order: 5

## Files

- `scores.csv`: raw eval_tpc parsed scores
- `score_details.csv`: scores plus pass counts and top failures
- `per_query_failures.csv`: per-query failure columns
- `generation_timing.csv/json`: fresh generation timings
- `raw_eval_outputs.json`: raw official eval stdout/stderr
