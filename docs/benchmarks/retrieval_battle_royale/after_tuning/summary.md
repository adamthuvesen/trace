# Retrieval Battle Royale Evaluation

**Label:** after_tuning
**Suite:** `tests/fixtures/eval_battle_royale.yaml`
**Judging:** deterministic expected-path metrics only; no LLM judges

## Aggregate by Mode

| Mode | Queries | Hit@1 | Hit@5 | MRR | p50 ms | p95 ms | Smart fallback | Top-1 failure buckets |
|------|---------|-------|-------|-----|--------|--------|----------------|-----------------------|
| bm25 | 35 | 94.3% | 97.1% | 0.957 | 0.1 | 0.4 | - | concepts: 1, features: 1 |
| semantic | 35 | 94.3% | 100.0% | 0.971 | 34.6 | 115.3 | - | concepts: 1, hybrid: 1 |
| hybrid | 35 | 100.0% | 100.0% | 1.000 | 33.1 | 100.7 | - | - |
| reranked | 35 | 100.0% | 100.0% | 1.000 | 29.9 | 131.7 | - | - |
| smart | 35 | 100.0% | 100.0% | 1.000 | 19.2 | 110.2 | 51.4% | - |

## By Knowledge Base

| KB | Mode | Queries | Hit@1 | Hit@5 | MRR | p50 ms | p95 ms | Smart fallback |
|----|------|---------|-------|-------|-----|--------|--------|----------------|
| retrieval | bm25 | 19 | 89.5% | 94.7% | 0.921 | 0.1 | 0.4 | - |
| retrieval | semantic | 19 | 94.7% | 100.0% | 0.974 | 28.9 | 84.0 | - |
| retrieval | hybrid | 19 | 100.0% | 100.0% | 1.000 | 33.3 | 145.9 | - |
| retrieval | reranked | 19 | 100.0% | 100.0% | 1.000 | 33.0 | 162.5 | - |
| retrieval | smart | 19 | 100.0% | 100.0% | 1.000 | 25.2 | 96.6 | 52.6% |
| support | bm25 | 8 | 100.0% | 100.0% | 1.000 | 0.2 | 0.3 | - |
| support | semantic | 8 | 100.0% | 100.0% | 1.000 | 36.3 | 127.3 | - |
| support | hybrid | 8 | 100.0% | 100.0% | 1.000 | 34.9 | 67.8 | - |
| support | reranked | 8 | 100.0% | 100.0% | 1.000 | 26.2 | 44.4 | - |
| support | smart | 8 | 100.0% | 100.0% | 1.000 | 9.8 | 42.7 | 50.0% |
| api | bm25 | 8 | 100.0% | 100.0% | 1.000 | 0.2 | 0.3 | - |
| api | semantic | 8 | 87.5% | 100.0% | 0.938 | 46.2 | 110.0 | - |
| api | hybrid | 8 | 100.0% | 100.0% | 1.000 | 23.8 | 41.0 | - |
| api | reranked | 8 | 100.0% | 100.0% | 1.000 | 37.9 | 94.1 | - |
| api | smart | 8 | 100.0% | 100.0% | 1.000 | 34.9 | 143.8 | 50.0% |

## Knowledge Bases

- **retrieval**: `tests/fixtures/eval_kb` with `tests/fixtures/eval_golden_queries.yaml`
- **support**: `tests/fixtures/battle_kbs/support_kb` with `tests/fixtures/battle_kbs/support_golden_queries.yaml`
- **api**: `tests/fixtures/battle_kbs/api_kb` with `tests/fixtures/battle_kbs/api_golden_queries.yaml`
