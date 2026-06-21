# Trace Retrieval Performance Loop

Date: 2026-06-21

This loop targeted the default `smart` retrieval path on the committed no-secret
multi-KB battle suite. The goal was to keep perfect deterministic path quality
while reducing local latency by at least 30%.

## Commands

Baseline:

```bash
TOKENIZERS_PARALLELISM=false uv run python -m tools.eval.battle_royale --label performance_loop_baseline --detail-reports
KB_PATH=tests/fixtures/eval_kb EVAL_GOLDEN_QUERIES=tests/fixtures/eval_golden_queries.yaml TOKENIZERS_PARALLELISM=false uv run python -m tools.eval.cli --full --search smart --output-dir docs/benchmarks/performance_loop_single_baseline
```

Final:

```bash
uv run ruff check .
env -u KB_PATH TOKENIZERS_PARALLELISM=false uv run python -m pytest tests/ -q
TOKENIZERS_PARALLELISM=false uv run python -m tools.eval.battle_royale --label performance_loop_after --detail-reports
KB_PATH=tests/fixtures/eval_kb EVAL_GOLDEN_QUERIES=tests/fixtures/eval_golden_queries.yaml TOKENIZERS_PARALLELISM=false uv run python -m tools.eval.cli --full --search smart --output-dir docs/benchmarks/performance_loop_single_after
```

One additional full-suite attempt was run with
`KB_PATH=tests/fixtures/eval_kb`; it failed one existing slow KB-backed format
test because that fixture intentionally contains only Markdown files:
`TestListDocumentsLogic.test_list_documents_includes_all_extensions`.

## Multi-KB Smart Results

| Run | Queries | Hit@1 | Hit@5 | MRR | p50 ms | p95 ms | Fallback |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `performance_loop_baseline` | 35 | 100.0% | 100.0% | 1.000 | 13.5 | 43.7 | 51.4% |
| `performance_loop_after` | 35 | 100.0% | 100.0% | 1.000 | 0.4 | 16.5 | 25.7% |

`smart` p95 improved by 62.3% and p50 improved by 97.0% on the same local
harness. Treat these as relative fixture numbers, not corpus-scale claims.

## Single-Fixture Smart Results

| Run | Queries | Top-1 Path | Top-5 Path | Top-1 Keyword | Top-5 Keyword | MRR | p50 ms | p95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `performance_loop_single_baseline` | 17 | 100.0% | 100.0% | 47.1% | 52.9% | 1.000 | 16.1 | 26.9 |
| `performance_loop_single_after` | 17 | 100.0% | 100.0% | 94.1% | 100.0% | 1.000 | 0.4 | 18.9 |

## Change

Two general heuristics changed:

- Semantic search now fetches the requested candidate count before its local
  lexical tie-break instead of over-fetching 3x on unfiltered queries.
- `smart` search now trusts a conceptual BM25 result when the top score is
  decisively ahead of the runner-up. Flat or duplicate-heavy BM25 results still
  fall back to hybrid retrieval.

An experiment that also shrank the non-reranked hybrid candidate pool was
rejected because it reduced multi-KB `smart` Hit@1 to 97.1%.
