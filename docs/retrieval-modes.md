# Retrieval modes

Trace exposes four retrieval modes.
The `search` operation selects `adaptive`.
All modes apply filters before ranking.

| Mode | Retrieval behavior | Useful for |
| --- | --- | --- |
| `bm25` | Scores lexical chunks and aggregates evidence per file | Identifiers, configuration keys, error codes, known terms |
| `semantic` | Scores normalized vectors and adds lexical evidence within the candidate pool | Paraphrases and conceptual lookups |
| `hybrid` | Fuses BM25 and semantic ranks per document | Queries that need both signals |
| `adaptive` | Uses BM25 when its leading document clearly wins, otherwise uses hybrid | Default application search |

## Adaptive routing

The confidence gate compares BM25's leading document with its runner-up.
The leading score must be at least 1.3 times the runner-up score.
A single BM25 match falls back to hybrid because it provides no runner-up comparison.
The source is `BM25_DOMINANCE_MARGIN` in `retrieval/query_profile.py`.

The gate requests at least two BM25 documents, even for `top_k=1`.
Hybrid retrieval keeps its separate candidate depths: `2 * top_k` BM25 documents and `4 * top_k` semantic chunks.
Semantic retrieval can inspect a larger internal pool for its lexical scoring.
The semantic fusion weight is 0.4, from `retrieval/search.py`.

When BM25 finds nothing, exact-token queries can return an empty result directly.
Other queries can use a hybrid fallback.
An unfiltered fallback must also satisfy the existing confidence rule in `AdaptiveSearch._fallback_confident`.
The response includes the selected strategy, reason, and fallback flag.

## BM25 evidence

BM25 scores chunks, then aggregates them per file.
A file receives its best chunk score and a saturating bonus for supporting chunks.
Title, alias, path, heading, and folder matches contribute metadata evidence.
A query that names a page can lift that page above a generic hub demotion.
`status: superseded` and `status: deprecated` apply the existing 0.7 multiplier.
The ranking constants and implementation live in `retrieval/search.py`.

Frontmatter YAML stays outside ranking text.
`title`, `aliases`, and `summary` contribute a card to the first chunk.
The card and chunk construction belong to `extraction/` and `indexing/index_builder.py`.

## Identity, order, and source freshness

`SearchHit` separates document identity, chunk identity, content, and score evidence.
`SearchResponse` preserves final ranking order.
Shared operations retain one generation per selected collection through routing, candidate retrieval, filtering, and neighbor lookup.
Multi-collection merging compares rank contributions instead of unrelated raw scores.
Typed response rendering preserves the supplied order when it groups snippets by document.
Legacy list-based context formatting retains its score sorting.

Public `.search()` methods preserve their dictionary result contracts.
Typed ranking uses `.rank()`, and adaptive typed retrieval uses `.response()`.
`TraceOperations.search_response()` composes collection retrieval and returns a typed response.
See [architecture.md](architecture.md) for module ownership.

Search uses indexed source metadata and captured text.
`get_document` reads the current source file.
`list_documents` scans current files.
Reindex after source changes to align search with those live reads.

## Battle suites

The committed fixtures are small public knowledge bases with lexical and paraphrase cases.
They provide regression evidence, not corpus-scale performance claims.

```bash
uv run --locked python -m tools.eval.battle_royale \
  --output-dir tools/eval/results/runs/battle --label local --detail-reports
uv run --locked python -m tools.eval.battle_royale \
  --suite tests/fixtures/eval_battle_royale_challenge.yaml \
  --output-dir tools/eval/results/runs/battle --label local-challenge --detail-reports
```

Both commands use scratch indexes.
See [evaluation.md](evaluation.md) for manifests, metric definitions, and baseline comparison rules.

## Historical challenge results

This table belongs to the 2026-09-29 investigation and its 61-query challenge population.
The before run used commit `e979fc5` on the same day.
The committed `challenge_current` summary predates that investigation and is stale.

| Mode | MRR before | MRR after | p50 after |
| --- | ---: | ---: | ---: |
| `bm25` | 0.833 | 0.833 | 0.1 ms |
| `semantic` | 0.919 | 0.919 | 4.5 ms |
| `hybrid` | 0.910 | 0.883 | 3.6 ms |
| `adaptive` | 0.870 | 0.878 | 3.5 ms |

These historical results use their original corpus, code, and measurement protocol.
The [benchmark note](benchmarks/2026-09-29-trace-overhaul.md) explains those experiments and their limits.
