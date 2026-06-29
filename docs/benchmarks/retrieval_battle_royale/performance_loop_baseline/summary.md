# Retrieval Battle Royale Evaluation

**Label:** performance_loop_baseline
**Suite:** `tests/fixtures/eval_battle_royale.yaml`
**Judging:** deterministic expected-path metrics only; no LLM judges

## Aggregate by Mode

| Mode | Queries | Hit@1 | Hit@5 | MRR | p50 ms | p95 ms | Adaptive fallback | Top-1 failure buckets |
|------|---------|-------|-------|-----|--------|--------|----------------|-----------------------|
| bm25 | 35 | 94.3% | 97.1% | 0.957 | 0.2 | 2.0 | - | concepts: 1, features: 1 |
| semantic | 35 | 94.3% | 100.0% | 0.971 | 17.7 | 36.3 | - | concepts: 1, hybrid: 1 |
| hybrid | 35 | 100.0% | 100.0% | 1.000 | 19.8 | 27.7 | - | - |
| reranked | 35 | 100.0% | 100.0% | 1.000 | 20.8 | 50.4 | - | - |
| adaptive | 35 | 100.0% | 100.0% | 1.000 | 13.5 | 43.7 | 51.4% | - |

## By Knowledge Base

| KB | Mode | Queries | Hit@1 | Hit@5 | MRR | p50 ms | p95 ms | Adaptive fallback |
|----|------|---------|-------|-------|-----|--------|--------|----------------|
| retrieval | bm25 | 19 | 89.5% | 94.7% | 0.921 | 0.2 | 0.3 | - |
| retrieval | semantic | 19 | 94.7% | 100.0% | 0.974 | 16.8 | 27.9 | - |
| retrieval | hybrid | 19 | 100.0% | 100.0% | 1.000 | 19.7 | 24.4 | - |
| retrieval | reranked | 19 | 100.0% | 100.0% | 1.000 | 21.4 | 48.4 | - |
| retrieval | adaptive | 19 | 100.0% | 100.0% | 1.000 | 19.7 | 39.1 | 52.6% |
| support | bm25 | 8 | 100.0% | 100.0% | 1.000 | 0.4 | 0.8 | - |
| support | semantic | 8 | 100.0% | 100.0% | 1.000 | 17.2 | 18.2 | - |
| support | hybrid | 8 | 100.0% | 100.0% | 1.000 | 21.1 | 22.9 | - |
| support | reranked | 8 | 100.0% | 100.0% | 1.000 | 20.4 | 56.5 | - |
| support | adaptive | 8 | 100.0% | 100.0% | 1.000 | 10.6 | 46.2 | 50.0% |
| api | bm25 | 8 | 100.0% | 100.0% | 1.000 | 1.2 | 2.3 | - |
| api | semantic | 8 | 87.5% | 100.0% | 0.938 | 27.0 | 62.3 | - |
| api | hybrid | 8 | 100.0% | 100.0% | 1.000 | 19.5 | 58.6 | - |
| api | reranked | 8 | 100.0% | 100.0% | 1.000 | 18.2 | 22.5 | - |
| api | adaptive | 8 | 100.0% | 100.0% | 1.000 | 7.1 | 33.0 | 50.0% |

## Knowledge Bases

- **retrieval**: `tests/fixtures/eval_kb` with `tests/fixtures/eval_golden_queries.yaml`
- **support**: `tests/fixtures/battle_kbs/support_kb` with `tests/fixtures/battle_kbs/support_golden_queries.yaml`
- **api**: `tests/fixtures/battle_kbs/api_kb` with `tests/fixtures/battle_kbs/api_golden_queries.yaml`
