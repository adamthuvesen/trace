# Retrieval Modes

Trace has five evaluated retrieval modes:

| Mode | Best use | Avoid when |
| --- | --- | --- |
| `bm25` | Exact identifiers, config keys, headers, error codes, filenames, and known terms. It is the fastest path by a wide margin. | The user is paraphrasing or does not know the vocabulary in the document. |
| `semantic` | Natural-language paraphrases and conceptual lookups when exact terms are missing. Semantic search now applies a small lexical tie-break across its vector candidates so exact titles and headers are not buried by near-topic matches. | You need deterministic exact-token behavior for API headers, status codes, env vars, or highly confusable adjacent concepts. |
| `hybrid` | Mixed lexical and semantic queries, especially technical noun phrases and queries with identifiers plus prose. | Ultra-low latency matters more than first-rank quality. |
| `reranked` | Final-quality shortlist ranking when a cross-encoder is acceptable. It uses the hybrid candidate set, then reranks candidates. | Default interactive search. The battle suite showed the same Hit@1 as hybrid with higher latency. |
| `adaptive` | Default MCP/CLI search. It starts with BM25, trusts strong lexical hits, and falls back to hybrid for conceptual or weak keyword results. | You are debugging one retrieval method in isolation. Use the specialist modes instead. |

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
| `adaptive` | 35 | 100.0% | 100.0% | 1.000 | 26.2ms |

Full reports:

- Baseline: `docs/benchmarks/retrieval_battle_royale/baseline/summary.md`
- After tuning: `docs/benchmarks/retrieval_battle_royale/after_tuning/summary.md`

No LLM judge is used. The suite uses deterministic expected-path metrics:
Hit@1, Hit@5, MRR, latency, and top-1 failure buckets.

## Challenge Suite

The default battle suite is small enough for smoke testing and is now saturated
for `adaptive` retrieval quality. Use the larger contrast-heavy suite when
tuning retrieval ranking:

```bash
TOKENIZERS_PARALLELISM=false uv run python -m tools.eval.battle_royale \
  --suite tests/fixtures/eval_battle_royale_challenge.yaml \
  --label challenge_current
```

Current challenge aggregate:

| Mode | Queries | Hit@1 | Hit@5 | MRR | p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `bm25` | 61 | 80.3% | 98.4% | 0.876 | 0.5ms |
| `semantic` | 61 | 82.0% | 100.0% | 0.903 | 20.3ms |
| `hybrid` | 61 | 86.9% | 100.0% | 0.929 | 39.2ms |
| `reranked` | 61 | 86.9% | 100.0% | 0.929 | 20.4ms |
| `adaptive` | 61 | 86.9% | 100.0% | 0.928 | 15.8ms |

Full challenge summary:

- Current: `docs/benchmarks/retrieval_battle_royale/challenge_current/summary.md`

The challenge suite adds stress queries for contrast and negation-heavy asks,
such as policy-versus-template, auth-versus-rate-limit, and RRF-versus-linear
combination. It is still a no-secret fixture suite, so treat numbers as relative
local signals rather than broad corpus claims.

## Defaults

No environment-variable default changed. `adaptive` remains the default user-facing
search path.

Two default heuristics changed because the battle suite showed repeatable misses:

- Identifier-heavy and dense technical noun-phrase queries now favor lexical
  weighting in hybrid/adaptive routing.
- Semantic search over-fetches a small vector candidate pool and applies a
  bounded lexical tie-break for exact titles, paths, and content overlap.
