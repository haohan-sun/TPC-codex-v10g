# Travel Planner Skill (demo1)

> Status: **documentation-only** — not auto-loaded by Claude Code or Codex.
> Must be read manually or referenced in prompts.

## When to use

When working on the `demo1` TPC travel planning agent for IJCAI 2026 ChinaTravel competition.

## Prohibited

- Do NOT use `hard_logic_py` in competition/official mode (only for local debug with `--oracle_translation`).
- Do NOT call external NLP/LLM APIs — all NL parsing must be offline.
- Do NOT write debug fields (`_internal`, `metadata`, `budget_report`, `repair_log`, `_invalid_intercity`) into official JSON output.
- Do NOT forge intercity `FlightID`/`TrainID` — must come from real WorldEnv/agent_env/JSON data.
- Do NOT retime real intercity transport — preserve original `start_time`/`end_time`/`price`/`cost`.

## Standard workflow

```
1. Load query
   python run_tpc.py --splits training --index <uid> --timeout 300

2. Parse constraints
   src/constraints/constraint_parser.py → LocalIntentParser (rule-based, offline)
   - NL text → ConstraintCard list
   - hard_logic_py DSL → ConstraintCard list (debug only)
   - Cover: pace, budget, hotel distance, forbidden/must-visit, cuisine, transport

3. Active query (optional, partial)
   src/active/active_query_selector.py → risk-driven data queries
   - Only query high-risk constraints (hotel distance, dining budget, transport)

4. Build candidates
   src/candidates/candidate_generator.py → POI/hotel/restaurant pools
   - Forbidden type hard-filtered, must-visit boosted

5. Multi-policy planning
   main.py → 5 policies: safe, budget, preference, low_transport, must_visit_first

6. Rolling day plan
   src/planner/plan_builder.py → per-day POI allocation + meal/accommodation/intercity

7. Day route optimization
   src/optimizer/day_route_optimizer.py → NN + 2-opt (attractions only)
   - Intercity activities preserved as-is (no retime)

8. Budget control
   src/scheduler/budget_controller.py → replace cheap restaurants/hotels, trim optional POIs

9. Local check + repair
   src/verifier/local_checker.py + src/repair/typed_repair.py

10. Official format output
    src/submission/ → strip debug fields, validate schema

11. Official eval
    cd ChinaTravel
    python eval_tpc.py --splits demo1_training_single --method TPCAgent_TPCLLM --lang en
```

## Input / Output

- **Input**: ChinaTravel query JSON with `uid`, `nature_language`, `start_city`, `target_city`, `days`, `people_number`
- **Output**: Official plan JSON with `people_number`, `start_city`, `target_city`, `itinerary[]`

## Common failures → fix module

| Failure | Module |
|---------|--------|
| Station name duplication | `day_route_optimizer._normalize_intercity_station` |
| Return transport wrong direction | `day_route_optimizer._retime_day` (outbound vs inbound) |
| Late arrival still schedules POIs | `plan_builder.build_full_plan_dict` (skip if arrival > 19:00) |
| Repeated restaurants across days | `plan_builder._select_restaurants` + `_used_restaurant_names` |
| Intercity overnight train timing | `select_intercity` → filter by departure time |
| Fake TrainID/FlightID | Rejected at `make_intercity_activity` + `select_intercity returns None` |
| 3-digit time hours | `add_minutes` raises RuntimeError on overflow |
| Schema time format | `format_checker.check_format` validates `^\d{2}:\d{2}$` |

## Test commands

```powershell
python -m compileall .
python src/constraints/test_constraints.py
python src/constraints/test_nl_parser.py
python src/data_layer/test_data_layer.py
python src/candidates/test_candidates.py
python src/active/test_active.py
python src/adapter/test_adapter.py
python run_tpc.py --splits training --index 20250324234255286741 --timeout 300

# Official eval
cd ChinaTravel
python eval_tpc.py --splits demo1_training_single --method TPCAgent_TPCLLM --lang en
```

## Current scores (2026-06-11)

```
Mic.EPR = 88.0
Overall = 17.6
Schema  = 100%
Hard logic = 100% (blocked by commonsense gate)
```

## Limitations

- `LocalIntentParser` wired into main pipeline via `constraint_parser.py`, but NLP is still rule-based (no offline model).
- Active SLAM generates actions but results are not fully consumed by candidates.
- MPC is not true receding horizon — POIs pre-allocated per day.
- Day route optimizer uses greedy+2-opt, not GA/ACO for production.
- Repair is field-level, not WorldEnv data-driven.
- This skill file is documentation-only — Claude Code does not auto-load it.
