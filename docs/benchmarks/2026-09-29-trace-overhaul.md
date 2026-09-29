# Trace overhaul, 2026-09-29

Adaptive search is more accurate on both real knowledge bases, cold starts are 8x faster, and a long-running server now picks up reindexes from other processes with exactly one writer per index. "Before" is commit `e979fc5`, "after" is the end of the series. Both were measured on the same machine on the same day.

## Corpora

| Corpus | Size | Cases | Notes |
| --- | --- | ---: | --- |
| Private wiki | 390 pages | 83 | Gate for this work. Run scoped to `wiki/` and unscoped. |
| Private team knowledge base | 29 docs | 18 | Guard against overfitting to the wiki. Fixture written from the docs without running Trace. |
| `tests/fixtures/eval_kb` | 24 docs | 17 | Committed smoke fixture, paraphrase-heavy. |
| Battle challenge suite | 3 fixture KBs | 61 | Committed, no-secret. |

Query texts for the private corpora stay private. Only aggregates are reported.

## Accuracy (MRR)

| Corpus | Mode | Before | After |
| --- | --- | ---: | ---: |
| Private wiki | `adaptive` (default) | 0.841 | **0.891** |
| | `bm25` | 0.841 | 0.864 |
| | `hybrid` | 0.782 | 0.892 |
| | `semantic` | 0.810 | 0.823 |
| Team KB | `adaptive` | 0.907 | **0.972** |
| | `bm25` | 0.907 | 0.972 |
| | `hybrid` | 0.833 | 1.000 |
| | `semantic` | 0.917 | 0.931 |
| Smoke fixture | `adaptive` | 0.941 | 0.941 |
| | `hybrid` | 0.971 | 0.941 |
| Challenge suite | `adaptive` | 0.870 | 0.878 |
| | `hybrid` | 0.910 | 0.883 |

Wiki numbers are unscoped. Scoped results match within 0.015.

Two regressions to know about:

- **Wiki success@10 is 0.988, down from 1.000.** One broad landscape question has no relevant page in the top 10 in any mode. Before, BM25 ranked one at 9th by luck.
- **Wiki evidence coverage is 0.897, down from 0.926.** Coverage is the share of all required pages found in the top 10. Fusion swaps some of BM25's lower-ranked pages for semantic ones on multi-page questions. The answer-quality run below shows no cost: required pages reached the generator's context in 10 of 10 cases.

Hybrid dropped on the smoke fixture and the challenge suite, which reward semantic search, while it gained 0.11 on the wiki and 0.17 on the team KB.

## Answer quality

The corpus owner's answer-quality benchmark (10 rubric cases, 5 linked pages): key-point coverage 0.681 against a 0.673 baseline (run-to-run noise is about ±0.04). Required context was fully covered in all 10 cases. One case errored on a judge timeout.

## Speed and resources

| Measure | Before | After |
| --- | ---: | ---: |
| Cold `trace search`, BM25 answers | 1.45 s | 0.18 s |
| Cold `trace search`, falls back (loads model) | 1.45 s | 0.35 s |
| Warm HTTP `tools/call`, three collections | 12.5 ms | 5.9 ms |
| Wiki p50, `adaptive` / `hybrid` / `bm25` | 6.9 / 14.3 / 4.9 ms | 9.7 / 3.6 / 2.2 ms |
| Forced rebuild, wiki | 25.8 s | 12.7 s |
| Peak memory during a forced wiki rebuild | 2.4 GB | 0.4 GB |
| Index on disk, three collections | 81 MB | 16 MB |

Adaptive p50 rose because it now fuses on a share of queries (22% on the team KB), where before it never did. The warm-call figures come from old and new servers run back to back over curl.

## What changed, and what each change bought

| Change | Evidence |
| --- | --- |
| Chroma replaced by immutable index generations, an atomic `CURRENT` swap, and one `flock` writer | Same rankings. A CLI reindex beside a running daemon is picked up on the next search, and a second writer fails with the holder's pid. Index 5x smaller, no 0.3 s Chroma import. |
| Semantic lexical boost re-ranks a 50-candidate vector pool | Wiki semantic success@10 0.904 to 0.964 at the time |
| Frontmatter parsed into a first-chunk card, YAML kept out of ranking text | Wiki BM25 MRR 0.841 to 0.853, together with the next two rows. Named pages and aliases resolve ("hobby builds" now returns its hub page first). |
| Query that names a page's title or alias ranks it first, including `index.md` hubs | Fixes the hub-page misses. Neutral on the eval sets. |
| `status: superseded` / `deprecated` pages score 0.7x | The replacement ranks first and the replaced page second. |
| Hybrid fuses per document instead of per chunk | Wiki hybrid 0.798 to 0.848, team KB 0.889 to 0.917 |
| Adaptive fuses unless BM25's top document scores at least 1.3x the runner-up | Wiki adaptive 0.853 to 0.872. Before, any title or breadcrumb overlap counted as confident, so it never fell back. |
| Chunks of 1,500 characters instead of 1,000 | Best of 1,000 / 1,500 / 2,000 on both real corpora. Team KB BM25 0.907 to 0.972. |
| Semantic fusion weight 0.4 | Wiki adaptive 0.878 to 0.891, team KB hybrid 0.972 to 1.000 |
| Memoized term extraction, lazy FastMCP import, batch-16 embedding | Latency and memory rows above |

## Rejected

| Tried | Result |
| --- | --- |
| Cross-encoder reranker (`ms-marco-MiniLM-L-6-v2`) | Wiki hybrid MRR 0.848 to 0.742, p50 20 ms to 265 ms. Removed, along with the torch backend and `sentence-transformers`. |
| Splitting chunks at H2 instead of H3 | Adaptive +0.007, semantic −0.032 |
| Chunks of 2,000 characters | Semantic −0.037 on the wiki, −0.061 on the team KB |
| Semantic fusion weight 0.3 or 0.5 | 0.4 matched or beat both on the real corpora |
| Per-query-type fusion weights (0.7 questions, 0.4 keywords) | Same as a flat weight on both real corpora. Removed. |

## Reproduce

The private-corpus numbers come from the corpus owner's own eval harness, which spawns `trace serve`
from this working tree. The committed fixtures reproduce anywhere:

```bash
KB_PATH=tests/fixtures/eval_kb EVAL_GOLDEN_QUERIES=tests/fixtures/eval_golden_queries.yaml \
  uv run python -m tools.eval.cli --full --search adaptive
uv run python -m tools.eval.battle_royale \
  --suite tests/fixtures/eval_battle_royale_challenge.yaml --label <label>
```

Run experiments against a scratch `INDEX_PATH` so they never touch indexes a running server serves.
