# Retrieval Battle Royale Evaluation

**Label:** performance_loop_after
**Suite:** `tests/fixtures/eval_battle_royale.yaml`
**Judging:** deterministic expected-path metrics only; no LLM judges

## Aggregate by Mode

| Mode | Queries | Hit@1 | Hit@5 | MRR | p50 ms | p95 ms | Smart fallback | Top-1 failure buckets |
|------|---------|-------|-------|-----|--------|--------|----------------|-----------------------|
| bm25 | 35 | 94.3% | 97.1% | 0.957 | 0.2 | 0.6 | - | concepts: 1, features: 1 |
| semantic | 35 | 94.3% | 100.0% | 0.971 | 13.8 | 28.7 | - | concepts: 1, hybrid: 1 |
| hybrid | 35 | 100.0% | 100.0% | 1.000 | 18.3 | 40.5 | - | - |
| reranked | 35 | 100.0% | 100.0% | 1.000 | 16.6 | 46.9 | - | - |
| smart | 35 | 100.0% | 100.0% | 1.000 | 0.4 | 16.5 | 25.7% | - |

## By Knowledge Base

| KB | Mode | Queries | Hit@1 | Hit@5 | MRR | p50 ms | p95 ms | Smart fallback |
|----|------|---------|-------|-------|-----|--------|--------|----------------|
| retrieval | bm25 | 19 | 89.5% | 94.7% | 0.921 | 0.2 | 0.5 | - |
| retrieval | semantic | 19 | 94.7% | 100.0% | 0.974 | 12.7 | 16.2 | - |
| retrieval | hybrid | 19 | 100.0% | 100.0% | 1.000 | 20.0 | 49.1 | - |
| retrieval | reranked | 19 | 100.0% | 100.0% | 1.000 | 13.6 | 19.5 | - |
| retrieval | smart | 19 | 100.0% | 100.0% | 1.000 | 0.5 | 16.4 | 31.6% |
| support | bm25 | 8 | 100.0% | 100.0% | 1.000 | 0.2 | 0.4 | - |
| support | semantic | 8 | 100.0% | 100.0% | 1.000 | 12.7 | 15.1 | - |
| support | hybrid | 8 | 100.0% | 100.0% | 1.000 | 15.3 | 27.2 | - |
| support | reranked | 8 | 100.0% | 100.0% | 1.000 | 22.3 | 25.7 | - |
| support | smart | 8 | 100.0% | 100.0% | 1.000 | 0.3 | 17.2 | 25.0% |
| api | bm25 | 8 | 100.0% | 100.0% | 1.000 | 0.2 | 0.7 | - |
| api | semantic | 8 | 87.5% | 100.0% | 0.938 | 20.1 | 37.2 | - |
| api | hybrid | 8 | 100.0% | 100.0% | 1.000 | 19.6 | 34.2 | - |
| api | reranked | 8 | 100.0% | 100.0% | 1.000 | 41.6 | 74.7 | - |
| api | smart | 8 | 100.0% | 100.0% | 1.000 | 0.2 | 10.5 | 12.5% |

## Knowledge Bases

- **retrieval**: `tests/fixtures/eval_kb` with `tests/fixtures/eval_golden_queries.yaml`
- **support**: `tests/fixtures/battle_kbs/support_kb` with `tests/fixtures/battle_kbs/support_golden_queries.yaml`
- **api**: `tests/fixtures/battle_kbs/api_kb` with `tests/fixtures/battle_kbs/api_golden_queries.yaml`
