# Phase 8 Acceptance Check — TEMP_GENERALIZE_V1

## Round 1 Criteria

| Criterion | Target | Actual | Status |
|-----------|:------:|:------:|:------:|
| training_rand10 Overall | >= 97 | 97.52 | ✅ |
| fresh ALL30 Overall | >= 40 | 16.69 | ❌ |
| commonsense_pass > 0 | Yes | 0/30 | ❌ |
| all_pass > 0 | Yes | 0/30 | ❌ |

**Result: Round 1 NOT passed.**

## Why C-LPR/FPR = 0

The official evaluator checks hard-logic constraints from `hard_logic_py` fields.
Our NL parser extracts constraints from `nature_language` only (as required).
The gap between what hard_logic_py specifies and what NL parser extracts is the
fundamental bottleneck.

### Hard_logic constraints our generator DOESN'T satisfy:
1. **Ticket counts**: `activity_tickets(activity)!=N` — most queries require specific ticket counts
2. **Innercity transport modes**: `innercity_transport_type(activity)=='metro'` restrictions
3. **Attraction cost limits**: `attraction_cost<=0` (free attractions) — parser handles this but planner doesn't enforce
4. **Intercity transport cost**: `inter_city_transportation_cost<=0` — free intercity constraint
5. **Specific attraction types**: `{"Museum/Memorial Hall"}<=attraction_type_set`

### What's needed to reach 40+:
1. **Better constraint extraction from NL** — mine correlation between nature_language phrases and hard_logic requirements
2. **Planner constraint enforcement** — actually apply ticket counts, transport restrictions, cost limits
3. **Post-generation hard-logic repair** — after plan is built, verify against the known constraint patterns

## Next Steps

The current approach (NL parser only, no hard_logic_py at runtime) has hit a wall at ~16.6.
To reach 40+, need either:
- Much more aggressive NL parser patterns
- Or a soft constraint classifier trained on hard_logic labels
- Or a post-generation verifier that tests hard-logic patterns

All test data in `test/generalization_v1/`.
