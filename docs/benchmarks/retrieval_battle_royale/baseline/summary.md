# Retrieval Battle Royale Evaluation

**Label:** baseline
**Suite:** `tests/fixtures/eval_battle_royale.yaml`
**Judging:** deterministic expected-path metrics only; no LLM judges

## Aggregate by Mode

| Mode | Queries | Hit@1 | Hit@5 | MRR | p50 ms | p95 ms | Adaptive fallback | Top-1 failure buckets |
|------|---------|-------|-------|-----|--------|--------|----------------|-----------------------|
| bm25 | 35 | 94.3% | 97.1% | 0.957 | 0.1 | 0.5 | - | concepts: 1, features: 1 |
| semantic | 35 | 94.3% | 100.0% | 0.971 | 35.1 | 89.0 | - | concepts: 1, hybrid: 1 |
| hybrid | 35 | 100.0% | 100.0% | 1.000 | 35.5 | 122.8 | - | - |
| reranked | 35 | 100.0% | 100.0% | 1.000 | 37.1 | 151.8 | - | - |
| adaptive | 35 | 100.0% | 100.0% | 1.000 | 8.5 | 51.5 | 51.4% | - |

## By Knowledge Base

| KB | Mode | Queries | Hit@1 | Hit@5 | MRR | p50 ms | p95 ms | Adaptive fallback |
|----|------|---------|-------|-------|-----|--------|--------|----------------|
| retrieval | bm25 | 19 | 89.5% | 94.7% | 0.921 | 0.1 | 0.3 | - |
| retrieval | semantic | 19 | 94.7% | 100.0% | 0.974 | 34.7 | 86.0 | - |
| retrieval | hybrid | 19 | 100.0% | 100.0% | 1.000 | 37.1 | 163.4 | - |
| retrieval | reranked | 19 | 100.0% | 100.0% | 1.000 | 31.7 | 150.1 | - |
| retrieval | adaptive | 19 | 100.0% | 100.0% | 1.000 | 13.2 | 55.5 | 52.6% |
| support | bm25 | 8 | 100.0% | 100.0% | 1.000 | 0.2 | 0.6 | - |
| support | semantic | 8 | 100.0% | 100.0% | 1.000 | 43.4 | 114.4 | - |
| support | hybrid | 8 | 100.0% | 100.0% | 1.000 | 34.3 | 69.2 | - |
| support | reranked | 8 | 100.0% | 100.0% | 1.000 | 40.8 | 50.6 | - |
| support | adaptive | 8 | 100.0% | 100.0% | 1.000 | 4.5 | 19.6 | 50.0% |
| api | bm25 | 8 | 100.0% | 100.0% | 1.000 | 0.1 | 0.3 | - |
| api | semantic | 8 | 87.5% | 100.0% | 0.938 | 33.0 | 60.0 | - |
| api | hybrid | 8 | 100.0% | 100.0% | 1.000 | 33.8 | 90.9 | - |
| api | reranked | 8 | 100.0% | 100.0% | 1.000 | 44.7 | 147.7 | - |
| api | adaptive | 8 | 100.0% | 100.0% | 1.000 | 9.5 | 43.4 | 50.0% |

## Knowledge Bases

- **retrieval**: `tests/fixtures/eval_kb` with `tests/fixtures/eval_golden_queries.yaml`
- **support**: `tests/fixtures/battle_kbs/support_kb` with `tests/fixtures/battle_kbs/support_golden_queries.yaml`
- **api**: `tests/fixtures/battle_kbs/api_kb` with `tests/fixtures/battle_kbs/api_golden_queries.yaml`
