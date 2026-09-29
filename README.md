# Trace

![License](https://img.shields.io/github/license/adamthuvesen/trace) ![Python](https://img.shields.io/badge/python-3.11%2B-blue)

Local retrieval over a folder of files, for an agent or for you. Trace indexes
documents on disk and serves search, document fetch, and diagnostics over a CLI
or an MCP server. That lets an agent pull the right passages from a knowledge
base without you pasting the whole thing into context.

The default `search` is adaptive and BM25-first. When BM25's top document
clearly leads the runner-up, Trace returns BM25's ranking. When it doesn't, it
fuses in semantic ranking per document. Retrieval runs entirely locally, and
embeddings run on-device (ONNX int8). Nothing leaves the machine.

The CLI and MCP server wrap the same Python primitives (`WikiIndexer`,
`AdaptiveSearch`, `CollectionRegistry`, and result formatters), so you can use
the pieces directly from a script or library.

Formats: Markdown, PDF, Word, PowerPoint, CSV, SQL, Python, YAML, TypeScript,
Jupyter notebooks.

## Install

Trace needs Python 3.11+ and `uv`.

```bash
uv sync
```

## Demo With A Committed Fixture

This command searches the committed fixture in `tests/fixtures/eval_kb`.

```console
$ KB_PATH=tests/fixtures/eval_kb uv run trace search "BM25 ranking" --top-k 2
Found 2 results

## Strategy
- **Selected:** hybrid
- **Fallback used:** yes
- **Reason:** BM25 matched only one document

## Context

### 1. BM25
- **Path:** `glossary/bm25.md`
- **Folder:** glossary
- **Source:** hybrid

**Snippet 1:** BM25
- **Match evidence:** title matches: bm25; path matches: bm25; breadcrumb matches: bm25
- **Matched terms:** `bm25`, `ranking`
- **Best quote:** Document: BM25 Folder: glossary # BM25 BM25 is a classic **keyword** ranking function for lexical retrieval...

### 2. Reranking
...

## Suggested Follow-ups
- `get_document(path="glossary/bm25.md")`
- `get_document(path="features/reranking.md")`
```

## CLI

Use `uv run trace ...` from the repo, or `trace ...` once installed.

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

With no subcommand, `uv run trace` starts the MCP server.

| Command | Description |
| --- | --- |
| `trace search "query"` | BM25-first search that fuses in semantic ranking when BM25 has no clear winner |
| `trace semantic-search "query"` | Vector similarity search |
| `trace keyword-search "term"` | Direct BM25 keyword search for exact terms |
| `trace hybrid-search "query"` | BM25 and semantic ranking fused per document |
| `trace get-document path/to/doc.md` | Fetch a document by path |
| `trace list-documents` | List documents, optionally by folder |
| `trace index-stats` | Show index status |
| `trace doctor "sample query"` | Diagnose config, visible docs, exclusions, indexes |
| `trace reindex` | Update indexes incrementally; `--force` to rebuild |
| `trace serve` | Start the MCP server (stdio; `--transport http` for a shared server) |

Search commands take `--top-k` (`keyword-search` uses `--max-results`);
`list-documents` takes `--folder` and `--limit`. Search commands and
`list-documents` also take `--path-prefix` (repeatable), `--extensions`
(`.md,.py`), and `--since` (ISO 8601) to scope results. Collection-aware
commands take `--collection`.

## MCP server

Trace speaks MCP over stdio by default. Point it at one collection with
`KB_PATH` or several named ones with `KB_COLLECTIONS`. The server name is
`trace`; tools are exposed as `mcp__trace__<tool>`.

Trace pins FastMCP 4.0.0b2 so clients can negotiate MCP `2026-07-28` or an
older protocol revision.

To share one long-lived server between many clients instead of spawning one
process per chat, serve streamable HTTP:

```bash
KB_COLLECTIONS="docs:/path/to/docs" \
  uv run trace serve --transport http --host 127.0.0.1 --port 7421
```

Clients connect to `http://127.0.0.1:7421/mcp`. The server is stateless (no
session ids to lose across a restart), has no authentication, and rejects
requests whose `Host` or `Origin` is not local, so keep it on a loopback
address.

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
  uv run fastmcp dev src/trace_search/server/trace_server.py
```

The tools map one-to-one onto the CLI:

| Tool | Description |
| --- | --- |
| `search` | BM25-first search that fuses in semantic ranking when BM25 has no clear winner (default) |
| `semantic_search` | Vector similarity search |
| `keyword_search` | Direct BM25 keyword search for exact terms |
| `search_hybrid` | BM25 and semantic ranking fused per document |
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

Start with `search`. It reports which strategy won, groups context by document,
includes match evidence, and suggests `get_document(path=...)` follow-ups. Reach
for `keyword_search` / `semantic_search` / `search_hybrid` when you want one
mode for debugging or deterministic comparison.

## Configuration

| Variable | Description | Default |
| --- | --- | --- |
| `KB_PATH` | Path to a single collection (`~` expanded) | unset |
| `KB_COLLECTIONS` | Comma-separated `name:path` pairs (`~` expanded) | unset |
| `INDEX_PATH` | Root path for indexes (`~` expanded) | unset |
| `LOG_LEVEL` | `DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL`/`NOTSET` | `INFO` |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` or `BAAI/bge-base-en-v1.5` | `all-MiniLM-L6-v2` |

`KB_PATH` and `KB_COLLECTIONS` are mutually exclusive. Setting both fails at
startup, as do invalid paths, collection names, and log levels.

Indexes live under each collection in `.mcp-search/indexes/`. Set `INDEX_PATH`
to store them elsewhere: single-collection mode writes there directly,
multi-collection mode uses one subdirectory per collection.

### Markdown frontmatter

Trace reads YAML frontmatter instead of indexing it as text. `title`,
`aliases`, and `summary` (or `name` and `description`) go into a short card
at the top of the first chunk, and every other key stays out of ranking. A
query that is a page's title or one of its aliases ranks that page first. A
page with `status: superseded` or `status: deprecated` ranks below its
replacement, and search output shows its status and `as_of` date.

```yaml
---
title: Release runbook
aliases: [deploy process, shipping checklist]
summary: How to cut, tag, verify, and roll back a release.
status: current
as_of: 2026-08-04
---
```

### Per-collection `.traceignore`

Trace always skips dot-prefixed paths and the global `EXCLUDE_PATTERNS`
directory names. To narrow one collection further, put a `.traceignore` at its
KB root. It uses gitignore syntax, including `!` negation, matched against the
KB-relative path, and document paths keep their prefix. This allowlist indexes
only `wiki/`, minus its log files:

```gitignore
/*
!/wiki/
/wiki/log.md
/wiki/log/
```

Edits take effect on the next scan without a restart. The next incremental
`reindex` removes files that became ignored, and `doctor` notes when the
file is active and counts what it excluded.

## Reindexing

`reindex` is incremental: Trace fingerprints each file (SHA-256 + mtime + size)
and re-embeds only what was added or changed; removed files drop out. Run
`trace reindex --force` (`force=true` over MCP) to rebuild every file after a
model change or to recover from corruption.

Each build writes a complete new index generation (chunks, an embedding matrix,
and the BM25 index) and then atomically points `CURRENT` at it. A running server
notices the new generation on its next search, so a CLI `reindex` beside a
long-lived daemon takes effect without a restart, and a failed build leaves the
previous generation serving. Only one process can reindex a collection at a
time: a second writer fails fast with the first one's pid. Searches never write
to an existing index; a collection with no index yet is built on first use.

`doctor` reports the next-reindex plan and a change summary:

```text
- Index status: stale
  - 1 added, 2 changed, 1 removed since last index.
  - Next `reindex` will run incrementally on changed files.
- Source changes since last index: unchanged=27, added=1, changed=2, removed=1
```

When given a sample query, `doctor` probes existing indexes only. It tells you
to `reindex` rather than building as a side effect.

## Retrieval quality

Trace includes an eval harness (`tools/eval/`) for golden-query checks. The committed fixture is a small, deliberately tricky smoke test: 24 short Markdown docs and 17 queries with near-duplicate concepts, exact-token lookups, and paraphrases.

| Mode | Top-1 | Top-5 | MRR | p50 | p95 |
| --- | --- | --- | --- | --- | --- |
| `bm25` | 82% | 88% | 0.853 | 0.13 ms | 0.3 ms |
| `semantic` | 100% | 100% | 1.000 | 3.23 ms | 3.7 ms |
| `hybrid` | 88% | 100% | 0.941 | 3.33 ms | 5.3 ms |
| `adaptive` | 88% | 100% | 0.941 | 3.48 ms | 4.8 ms |

The fixture is paraphrase-heavy, so semantic search wins it. On real knowledge
bases BM25 usually leads: on an 83-case private wiki eval, `adaptive` scores
0.878 MRR against 0.864 for BM25 alone and 0.823 for semantic. The
[2026-09-29 benchmark note](docs/benchmarks/2026-09-29-trace-overhaul.md) has
the full numbers and what each change bought.

Reproduce the fixture numbers with:

```bash
KB_PATH=tests/fixtures/eval_kb EVAL_GOLDEN_QUERIES=tests/fixtures/eval_golden_queries.yaml \
  uv run python -m tools.eval.cli --full --search adaptive
```

For the multi-KB battle suite, see
[`docs/retrieval-modes.md`](docs/retrieval-modes.md).

## Development

```bash
uv run python -m pytest -m "not slow"        # skip embedding tests
uv run python scripts/check_module_sizes.py  # no module > 1000 lines
uv run ruff check .
uv build

# Search evaluation against the committed fixture
KB_PATH=tests/fixtures/eval_kb EVAL_GOLDEN_QUERIES=tests/fixtures/eval_golden_queries.yaml \
  uv run python -m tools.eval.cli --full --search adaptive
```

To evaluate against your own corpus, copy
`tools/eval/golden_queries.example.yaml` to `tools/eval/golden_queries.yaml`,
point `KB_PATH` at the matching docs, build the index, then run
`uv run python -m tools.eval.cli --quick`.
