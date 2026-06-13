# Trace

Local retrieval over a folder of files, for an agent or for you. Trace indexes
documents on disk and serves search, document fetch, and diagnostics over a CLI
or an MCP server — so an agent can pull the right passages from a knowledge base
without you pasting the whole thing into context.

Retrieval runs entirely locally. The default `search` is BM25-first: lexical
matching answers most queries fast, and Trace only falls back to vector/hybrid
when the keyword results look weak. Embeddings run on-device (ONNX int8 by
default); nothing leaves the machine.

Formats: Markdown, PDF, Word, PowerPoint, CSV, SQL, Python, YAML, TypeScript,
Jupyter notebooks.

## Install

Python 3.11+ and `uv`.

```bash
uv sync
```

## CLI

`uv run trace ...` from the repo, or `trace ...` once installed.

```bash
# Single collection
KB_PATH=/path/to/docs uv run trace search "sample query"

# Named collections
KB_COLLECTIONS="docs:/path/to/docs,team:/path/to/second-kb" \
  uv run trace search "sample query" --collection docs

# Check setup
KB_PATH=/path/to/docs uv run trace doctor

# Start the MCP server
KB_PATH=/path/to/docs uv run trace serve
```

Bare `uv run trace` also starts the MCP server (backward compatibility).

| Command | Description |
| --- | --- |
| `trace search "query"` | BM25-first search with semantic/hybrid fallback |
| `trace semantic-search "query"` | Vector similarity search |
| `trace keyword-search "term"` | Direct BM25 keyword search for exact terms |
| `trace hybrid-search "query"` | Semantic + keyword combined |
| `trace get-document path/to/doc.md` | Fetch a document by path |
| `trace list-documents` | List documents, optionally by folder |
| `trace index-stats` | Show index status |
| `trace doctor "sample query"` | Diagnose config, visible docs, exclusions, indexes |
| `trace reindex` | Update indexes incrementally; `--force` to rebuild |
| `trace serve` | Start the MCP server |

Search commands take `--top-k` (`keyword-search` uses `--max-results`);
`list-documents` takes `--folder` and `--limit`. Search commands and
`list-documents` also take `--path-prefix` (repeatable), `--extensions`
(`.md,.py`), and `--since` (ISO 8601) to scope results. Collection-aware
commands take `--collection`.

## MCP server

Trace speaks MCP over stdio. Point it at one collection with `KB_PATH` or
several named ones with `KB_COLLECTIONS`. The server name is `trace`; tools are
exposed as `mcp__trace__<tool>`.

### Claude Code

```bash
claude mcp add trace \
  --transport stdio \
  --env KB_COLLECTIONS="docs:/path/to/docs,team:/path/to/second-kb" \
  -- uv run --directory /path/to/trace trace serve
```

```bash
# Inspector
KB_COLLECTIONS="docs:/path/to/docs,team:/path/to/second-kb" \
  uv run fastmcp dev src/trace_search/trace_server.py
```

The tools map one-to-one onto the CLI:

| Tool | Description |
| --- | --- |
| `search` | BM25-first search with semantic/hybrid fallback (default) |
| `semantic_search` | Vector similarity search |
| `keyword_search` | Direct BM25 keyword search for exact terms |
| `search_hybrid` | Semantic + keyword combined |
| `get_document` | Fetch a document by path |
| `list_documents` | List documents, optionally by folder |
| `index_stats` | Show index status |
| `doctor` | Diagnose config, visible docs, exclusions, indexes |
| `reindex` | Update indexes incrementally; `force=true` to rebuild |

In multi-collection mode, search and document tools take an optional
`collection`. Search tools and `list_documents` take the same
`path_prefix` / `extensions` / `since` filters as the CLI; filters combine with
AND and show up in `search` output under `Active filters`, so an empty result
explains itself.

Start with `search` — it reports which strategy won, groups context by document,
includes match evidence, and suggests `get_document(path=...)` follow-ups. Reach
for `keyword_search` / `semantic_search` / `search_hybrid` when you want one
mode for debugging or deterministic comparison.

## Configuration

| Variable | Description | Default |
| --- | --- | --- |
| `KB_PATH` | Path to a single collection (`~` expanded) | — |
| `KB_COLLECTIONS` | Comma-separated `name:path` pairs (`~` expanded) | — |
| `INDEX_PATH` | Root path for indexes (`~` expanded) | — |
| `LOG_LEVEL` | `DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL`/`NOTSET` | `INFO` |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` or `BAAI/bge-base-en-v1.5` | `all-MiniLM-L6-v2` |
| `EMBEDDING_BACKEND` | `onnx` (int8, faster) or `torch` | `onnx` |
| `EMBEDDING_WARMUP_ENABLED` | Pre-encode at startup to cut first-query latency | `true` |
| `RERANKER_ENABLED` | Enable reranking | `false` |

`KB_PATH` and `KB_COLLECTIONS` are mutually exclusive — setting both fails at
startup, as do invalid paths, collection names, and log levels.

Indexes live under each collection in `.mcp-search/indexes/`. Set `INDEX_PATH`
to store them elsewhere: single-collection mode writes there directly,
multi-collection mode uses one subdirectory per collection.

## Reindexing

`reindex` is incremental: Trace fingerprints each file (SHA-256 + mtime + size)
and reprocesses only what was added, changed, or removed. Run
`trace reindex --force` (`force=true` over MCP) to drop both indexes and rebuild
from scratch — after a model change or to recover from corruption.

`doctor` reports the next-reindex plan and a change summary:

```text
- Index status: stale
  - 1 added, 2 changed, 1 removed since last index.
  - Next `reindex` will run incrementally on changed files.
- Source changes since last index: unchanged=27, added=1, changed=2, removed=1
```

When given a sample query, `doctor` probes existing indexes only — it tells you
to `reindex` rather than building as a side effect. If it reports unknown
metadata (an older `v1` schema), one `reindex` repopulates model and freshness
metadata; that run is forced, later runs are incremental.

## Retrieval quality

Trace ships an evaluation harness (`tools/eval/`) that runs a golden query set
through each search mode and scores path accuracy, MRR, and latency. The numbers
below come from the committed fixture — **8 short Markdown docs and an 8-query
"what is X?" golden set** — so read them as a smoke signal, not a corpus-scale
benchmark.

| Mode | Top-1 path | Top-5 path | MRR | p50 | p95 |
| --- | --- | --- | --- | --- | --- |
| `bm25` | 100% | 100% | 1.000 | 0.2 ms | 10.6 ms |
| `semantic` | 100% | 100% | 1.000 | 7.8 ms | 10.6 ms |
| `hybrid` | 100% | 100% | 1.000 | 8.5 ms | 19.1 ms |
| `smart` | 100% | 100% | 1.000 | 7.6 ms | 17.9 ms |

The corpus is too small and too clean to separate the modes on accuracy — each
retrieves the right document for all 8 queries. What differs is cost and routing:
pure `bm25` answers in ~0.2 ms p50, and because the golden queries are all
conceptual against a tiny corpus, `smart` judges BM25 too thin on every one and
falls back to vector search (100% fallback rate) — so here it tracks
`hybrid`/`semantic` latency rather than BM25's sub-millisecond path. On a larger
corpus with exact-term queries, that fallback rate drops and `smart` keeps the
fast lexical route. Latencies are microbenchmarks over 8 queries on one machine
(Apple Silicon, ONNX int8); treat them as relative, not absolute.

Full per-mode reports live in [`docs/benchmarks/`](docs/benchmarks/). Reproduce
any row, or `--ci` (the gate CI runs on every PR):

```bash
KB_PATH=tests/fixtures/eval_kb EVAL_GOLDEN_QUERIES=tests/fixtures/eval_golden_queries.yaml \
  uv run python -m tools.eval.cli --full --search smart --output-dir docs/benchmarks/
```

## Development

```bash
uv run python -m pytest -m "not slow"        # skip embedding tests
uv run python scripts/check_module_sizes.py  # no module > 1000 lines
uv run ruff check .
uv build

# Search evaluation against the committed fixture
KB_PATH=tests/fixtures/eval_kb EVAL_GOLDEN_QUERIES=tests/fixtures/eval_golden_queries.yaml \
  uv run python -m tools.eval.cli --full --search smart
```

To evaluate against your own corpus, copy
`tools/eval/golden_queries.example.yaml` to `tools/eval/golden_queries.yaml`,
point `KB_PATH` at the matching docs, build the index, then run
`uv run python -m tools.eval.cli --quick`.
