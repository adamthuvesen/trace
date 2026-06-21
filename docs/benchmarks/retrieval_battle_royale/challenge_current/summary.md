# Retrieval Battle Royale Evaluation

**Label:** challenge_current
**Suite:** `tests/fixtures/eval_battle_royale_challenge.yaml`
**Judging:** deterministic expected-path metrics only; no LLM judges

## Aggregate by Mode

| Mode | Queries | Hit@1 | Hit@5 | MRR | p50 ms | p95 ms | Smart fallback | Top-1 failure buckets |
|------|---------|-------|-------|-----|--------|--------|----------------|-----------------------|
| bm25 | 61 | 80.3% | 98.4% | 0.876 | 0.2 | 0.5 | - | concepts: 1, contrast: 10, features: 1 |
| semantic | 61 | 82.0% | 100.0% | 0.903 | 12.6 | 20.3 | - | concepts: 1, contrast: 9, hybrid: 1 |
| hybrid | 61 | 86.9% | 100.0% | 0.929 | 14.3 | 39.2 | - | contrast: 8 |
| reranked | 61 | 86.9% | 100.0% | 0.929 | 14.8 | 20.4 | - | contrast: 8 |
| smart | 61 | 86.9% | 100.0% | 0.928 | 0.5 | 15.8 | 34.4% | contrast: 8 |

## By Knowledge Base

| KB | Mode | Queries | Hit@1 | Hit@5 | MRR | p50 ms | p95 ms | Smart fallback |
|----|------|---------|-------|-------|-----|--------|--------|----------------|
| retrieval | bm25 | 29 | 69.0% | 96.6% | 0.796 | 0.2 | 0.4 | - |
| retrieval | semantic | 29 | 82.8% | 100.0% | 0.905 | 11.7 | 15.5 | - |
| retrieval | hybrid | 29 | 82.8% | 100.0% | 0.908 | 14.0 | 17.7 | - |
| retrieval | reranked | 29 | 82.8% | 100.0% | 0.908 | 14.8 | 17.5 | - |
| retrieval | smart | 29 | 82.8% | 100.0% | 0.905 | 0.5 | 15.5 | 41.4% |
| support | bm25 | 16 | 93.8% | 100.0% | 0.958 | 0.2 | 0.5 | - |
| support | semantic | 16 | 87.5% | 100.0% | 0.927 | 15.7 | 30.0 | - |
| support | hybrid | 16 | 93.8% | 100.0% | 0.958 | 16.3 | 58.4 | - |
| support | reranked | 16 | 93.8% | 100.0% | 0.958 | 14.5 | 23.2 | - |
| support | smart | 16 | 93.8% | 100.0% | 0.958 | 0.5 | 15.8 | 37.5% |
| api | bm25 | 16 | 87.5% | 100.0% | 0.938 | 0.2 | 0.5 | - |
| api | semantic | 16 | 75.0% | 100.0% | 0.875 | 13.3 | 19.9 | - |
| api | hybrid | 16 | 87.5% | 100.0% | 0.938 | 14.4 | 18.0 | - |
| api | reranked | 16 | 87.5% | 100.0% | 0.938 | 15.9 | 20.8 | - |
| api | smart | 16 | 87.5% | 100.0% | 0.938 | 0.4 | 17.2 | 18.8% |

## Knowledge Bases

- **retrieval**: `tests/fixtures/eval_kb` with `tests/fixtures/eval_golden_queries.yaml`
- **support**: `tests/fixtures/battle_kbs/support_kb` with `tests/fixtures/battle_kbs/support_golden_queries.yaml`
- **api**: `tests/fixtures/battle_kbs/api_kb` with `tests/fixtures/battle_kbs/api_golden_queries.yaml`
