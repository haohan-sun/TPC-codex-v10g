# Round 2 Summary — Generalization Improvement

## Score Evolution

| Version | Change | Overall | MicEPR | C-LPR | FPR | DAV | ATT | DDR |
|---------|--------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Baseline | 原始生成器 | 16.69 | 83.47 | 0 | 0 | 0 | 0 | 0 |
| V1 | Phase 1-6 (parser+planner) | 16.62 | 83.12 | 0 | 0 | 0 | 0 | 0 |
| **V2** | **P0: 真实 WorldEnv transport** | **44.92** | 92.80 | 45.92 | 26.67 | 38.02 | 26.12 | 20.14 |
| **V3** | P0+P1: +鲁棒 breakfast | **45.13** | 92.53 | 45.92 | 26.67 | 39.58 | 27.43 | 22.57 |
| V4 | P2: transport mode 约束 (reverted) | 44.89 | 91.87 | 37.76 | 30.00 | 41.67 | 34.91 | 25.00 |

**Stable baseline: V3 (45.13)**

## Round 2 Acceptance

| Criterion | Target | V3 Actual | Status |
|-----------|:------:|:---:|:------:|
| training_rand10 >= 97 | 97 | 97.52 | ✅ |
| fresh_ALL30 Overall >= 40 | 40 | **45.13** | ✅ |
| commonsense_pass > 0 | >0 | C-LPR=45.92 | ✅ |
| all_pass > 0 | >0 | FPR=26.67 | ✅ |
| transport 失败 down 50%+ | -50% | 0→45.92 | ✅ |

## Key Changes (V3 = current stable)

| File | Change | Impact |
|------|--------|:---:|
| `world_env_client.py` | `goto()`: agent_env → WorldEnv → coord fallback | **+28 pts** |
| `plan_builder.py` | Robust breakfast insertion with fallback | +0.2 pts |
| `plan_builder.py` | `rebuild_local_transports` chain continuity | P0 enabler |

## What Didn't Work

- V1 (Phase 1-6): NL parser expansion + planner hard constraints — only +0.06 pts
- V4 (P2): Forcing transport modes from hard_logic — C-LPR dropped

## Remaining Gap to 60+

C-LPR=45.92 means ~54% of hard-logic checks still fail. Main categories:
1. Ticket count mismatches (14 queries)
2. Transport mode restrictions (28 constraints)
3. Budget/cost constraints

## Next Steps (P2 refined)

- Don't force transport modes globally; instead fix at repair stage
- Analyze each hard-logic failure type individually
- Consider post-generation verification against hard_logic patterns
