# Retrieval Battle Royale Evaluation

**Label:** baseline
**Suite:** `tests/fixtures/eval_battle_royale.yaml`
**Judging:** deterministic expected-path metrics only; no LLM judges

## Aggregate by Mode

| Mode | Queries | Hit@1 | Hit@5 | MRR | p50 ms | p95 ms | Smart fallback | Top-1 failure buckets |
|------|---------|-------|-------|-----|--------|--------|----------------|-----------------------|
| bm25 | 35 | 94.3% | 97.1% | 0.957 | 0.2 | 0.7 | - | concepts: 1, features: 1 |
| semantic | 35 | 88.6% | 100.0% | 0.943 | 9.4 | 33.4 | - | concepts: 3, hybrid: 1 |
| hybrid | 35 | 88.6% | 100.0% | 0.943 | 8.8 | 30.9 | - | concepts: 3, hybrid: 1 |
| reranked | 35 | 88.6% | 100.0% | 0.943 | 12.5 | 47.2 | - | concepts: 3, hybrid: 1 |
| smart | 35 | 88.6% | 100.0% | 0.943 | 8.7 | 14.1 | 82.9% | concepts: 3, hybrid: 1 |

## By Knowledge Base

| KB | Mode | Queries | Hit@1 | Hit@5 | MRR | p50 ms | p95 ms | Smart fallback |
|----|------|---------|-------|-------|-----|--------|--------|----------------|
| retrieval | bm25 | 19 | 89.5% | 94.7% | 0.921 | 0.2 | 0.3 | - |
| retrieval | semantic | 19 | 84.2% | 100.0% | 0.921 | 8.9 | 11.1 | - |
| retrieval | hybrid | 19 | 84.2% | 100.0% | 0.921 | 8.2 | 12.6 | - |
| retrieval | reranked | 19 | 84.2% | 100.0% | 0.921 | 17.9 | 72.9 | - |
| retrieval | smart | 19 | 84.2% | 100.0% | 0.921 | 9.0 | 17.2 | 78.9% |
| support | bm25 | 8 | 100.0% | 100.0% | 1.000 | 0.2 | 0.3 | - |
| support | semantic | 8 | 100.0% | 100.0% | 1.000 | 9.4 | 10.1 | - |
| support | hybrid | 8 | 100.0% | 100.0% | 1.000 | 8.6 | 9.9 | - |
| support | reranked | 8 | 100.0% | 100.0% | 1.000 | 8.0 | 11.4 | - |
| support | smart | 8 | 100.0% | 100.0% | 1.000 | 8.2 | 9.3 | 87.5% |
| api | bm25 | 8 | 100.0% | 100.0% | 1.000 | 0.3 | 1.0 | - |
| api | semantic | 8 | 87.5% | 100.0% | 0.938 | 27.6 | 49.0 | - |
| api | hybrid | 8 | 87.5% | 100.0% | 0.938 | 16.6 | 31.6 | - |
| api | reranked | 8 | 87.5% | 100.0% | 0.938 | 7.1 | 13.8 | - |
| api | smart | 8 | 87.5% | 100.0% | 0.938 | 7.8 | 12.0 | 87.5% |

## Knowledge Bases

- **retrieval**: `tests/fixtures/eval_kb` with `tests/fixtures/eval_golden_queries.yaml`
- **support**: `tests/fixtures/battle_kbs/support_kb` with `tests/fixtures/battle_kbs/support_golden_queries.yaml`
- **api**: `tests/fixtures/battle_kbs/api_kb` with `tests/fixtures/battle_kbs/api_golden_queries.yaml`
