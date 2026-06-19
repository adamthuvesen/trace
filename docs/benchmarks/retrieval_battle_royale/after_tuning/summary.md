# Retrieval Battle Royale Evaluation

**Label:** after_tuning
**Suite:** `tests/fixtures/eval_battle_royale.yaml`
**Judging:** deterministic expected-path metrics only; no LLM judges

## Aggregate by Mode

| Mode | Queries | Hit@1 | Hit@5 | MRR | p50 ms | p95 ms | Smart fallback | Top-1 failure buckets |
|------|---------|-------|-------|-----|--------|--------|----------------|-----------------------|
| bm25 | 35 | 94.3% | 97.1% | 0.957 | 0.2 | 0.4 | - | concepts: 1, features: 1 |
| semantic | 35 | 94.3% | 100.0% | 0.971 | 11.5 | 30.7 | - | concepts: 1, hybrid: 1 |
| hybrid | 35 | 100.0% | 100.0% | 1.000 | 9.5 | 31.6 | - | - |
| reranked | 35 | 100.0% | 100.0% | 1.000 | 9.6 | 44.3 | - | - |
| smart | 35 | 100.0% | 100.0% | 1.000 | 7.8 | 26.2 | 51.4% | - |

## By Knowledge Base

| KB | Mode | Queries | Hit@1 | Hit@5 | MRR | p50 ms | p95 ms | Smart fallback |
|----|------|---------|-------|-------|-----|--------|--------|----------------|
| retrieval | bm25 | 19 | 89.5% | 94.7% | 0.921 | 0.2 | 0.5 | - |
| retrieval | semantic | 19 | 94.7% | 100.0% | 0.974 | 11.8 | 37.6 | - |
| retrieval | hybrid | 19 | 100.0% | 100.0% | 1.000 | 12.6 | 26.8 | - |
| retrieval | reranked | 19 | 100.0% | 100.0% | 1.000 | 9.3 | 13.8 | - |
| retrieval | smart | 19 | 100.0% | 100.0% | 1.000 | 7.8 | 10.4 | 52.6% |
| support | bm25 | 8 | 100.0% | 100.0% | 1.000 | 0.2 | 0.4 | - |
| support | semantic | 8 | 100.0% | 100.0% | 1.000 | 9.2 | 15.1 | - |
| support | hybrid | 8 | 100.0% | 100.0% | 1.000 | 23.0 | 40.8 | - |
| support | reranked | 8 | 100.0% | 100.0% | 1.000 | 26.9 | 65.6 | - |
| support | smart | 8 | 100.0% | 100.0% | 1.000 | 8.8 | 64.2 | 50.0% |
| api | bm25 | 8 | 100.0% | 100.0% | 1.000 | 0.1 | 0.3 | - |
| api | semantic | 8 | 87.5% | 100.0% | 0.938 | 11.1 | 18.5 | - |
| api | hybrid | 8 | 100.0% | 100.0% | 1.000 | 7.8 | 8.9 | - |
| api | reranked | 8 | 100.0% | 100.0% | 1.000 | 8.4 | 10.1 | - |
| api | smart | 8 | 100.0% | 100.0% | 1.000 | 4.1 | 13.3 | 50.0% |

## Knowledge Bases

- **retrieval**: `tests/fixtures/eval_kb` with `tests/fixtures/eval_golden_queries.yaml`
- **support**: `tests/fixtures/battle_kbs/support_kb` with `tests/fixtures/battle_kbs/support_golden_queries.yaml`
- **api**: `tests/fixtures/battle_kbs/api_kb` with `tests/fixtures/battle_kbs/api_golden_queries.yaml`
