# Retrieval Modes

Trace has five evaluated retrieval modes:

| Mode | Best use | Avoid when |
| --- | --- | --- |
| `bm25` | Exact identifiers, config keys, headers, error codes, filenames, and known terms. It is the fastest path by a wide margin. | The user is paraphrasing or does not know the vocabulary in the document. |
| `semantic` | Natural-language paraphrases and conceptual lookups when exact terms are missing. Semantic search now applies a small lexical tie-break across its vector candidates so exact titles and headers are not buried by near-topic matches. | You need deterministic exact-token behavior for API headers, status codes, env vars, or highly confusable adjacent concepts. |
| `hybrid` | Mixed lexical and semantic queries, especially technical noun phrases and queries with identifiers plus prose. | Ultra-low latency matters more than first-rank quality. |
| `reranked` | Final-quality shortlist ranking when a cross-encoder is acceptable. It uses the hybrid candidate set, then reranks candidates. | Default interactive search; the battle suite showed the same Hit@1 as hybrid with higher latency. |
| `smart` | Default MCP/CLI search. It starts with BM25, trusts strong lexical hits, and falls back to hybrid for conceptual or weak keyword results. | You are debugging one retrieval method in isolation. Use the specialist modes instead. |

## Battle Results

The multi-KB battle suite covers the committed retrieval fixture plus two
additional no-secret fixtures:

- `tests/fixtures/eval_kb`
- `tests/fixtures/battle_kbs/support_kb`
- `tests/fixtures/battle_kbs/api_kb`

Run it with:

```bash
TOKENIZERS_PARALLELISM=false uv run python -m tools.eval.battle_royale --label after_tuning
```

Final after-tuning aggregate:

| Mode | Queries | Hit@1 | Hit@5 | MRR | p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `bm25` | 35 | 94.3% | 97.1% | 0.957 | 0.4ms |
| `semantic` | 35 | 94.3% | 100.0% | 0.971 | 30.7ms |
| `hybrid` | 35 | 100.0% | 100.0% | 1.000 | 31.6ms |
| `reranked` | 35 | 100.0% | 100.0% | 1.000 | 44.3ms |
| `smart` | 35 | 100.0% | 100.0% | 1.000 | 26.2ms |

Full reports:

- Baseline: `docs/benchmarks/retrieval_battle_royale/baseline/summary.md`
- After tuning: `docs/benchmarks/retrieval_battle_royale/after_tuning/summary.md`

No LLM judge is used. The suite uses deterministic expected-path metrics:
Hit@1, Hit@5, MRR, latency, and top-1 failure buckets.

## Defaults

No environment-variable default changed. `smart` remains the default user-facing
search path.

Two default heuristics changed because the battle suite showed repeatable misses:

- Identifier-heavy and dense technical noun-phrase queries now favor lexical
  weighting in hybrid/smart routing.
- Semantic search over-fetches a small vector candidate pool and applies a
  bounded lexical tie-break for exact titles, paths, and content overlap.
