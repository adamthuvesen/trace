# Trace

Local retrieval for file-backed knowledge bases. Indexes documents on disk and exposes search, document, index, and diagnostic operations through a CLI or MCP server. 

Search modes:
- BM25 keyword matching
- Vector semantic search
- Smart (default): starts lexical, falls back to hybrid when results look weak

Supported formats: Markdown, PDF, Word, PowerPoint, CSV, SQL, Python, YAML, TypeScript, Jupyter notebooks.

## What Trace Does

- indexes one or more local document collections
- stores reusable BM25 and ChromaDB indexes beside the collection, or under a
  configured index root
- exposes keyword, semantic, hybrid, and smart search tools
- retrieves full source documents by path
- diagnoses corpus visibility, index health, exclusions, and sample queries

## When To Use It

Use Trace when an agent needs reliable access to a local folder of docs, notes,
code-adjacent knowledge, exports, or team material without sending the whole
collection into context.

## Install

Requires Python 3.11+ and `uv`.

```bash
uv sync
```

## CLI

Use `uv run trace ...` from this repo, or `trace ...` when installed.

```bash
# Search a single collection
KB_PATH=/path/to/your/docs uv run trace search "sample query"

# Search multiple named collections
KB_COLLECTIONS="docs:/path/to/docs,team-docs:/path/to/second-kb" \
uv run trace search "sample query" --collection docs

# Diagnose setup
KB_PATH=/path/to/your/docs uv run trace doctor

# Start the MCP server from the CLI
KB_PATH=/path/to/your/docs uv run trace serve
```

Bare `uv run trace` still starts the MCP server for backward compatibility.

| Command | Description |
| --- | --- |
| `trace search "query"` | Smart BM25-first search with semantic/hybrid fallback |
| `trace semantic-search "query"` | Vector similarity search |
| `trace keyword-search "term"` | Direct BM25 keyword search for exact terms |
| `trace hybrid-search "query"` | Semantic + keyword combined |
| `trace get-document path/to/doc.md` | Fetch a document by path |
| `trace list-documents` | List documents, optionally by folder |
| `trace index-stats` | Show index status |
| `trace doctor "sample query"` | Diagnose config, visible docs, exclusions, indexes, and sample queries |
| `trace reindex` | Update indexes incrementally; `--force` to rebuild from scratch |
| `trace serve` | Start the MCP server |

Collection-aware commands accept `--collection docs`. Search commands accept
`--top-k`; `keyword-search` uses `--max-results`; `list-documents` supports
`--folder` and `--limit`. All search commands and `list-documents` also accept
`--path-prefix` (repeatable), `--extensions` (e.g. `.md,.py`), and `--since`
(ISO 8601 datetime) to scope results.

## Connect An Agent

Trace currently speaks MCP over stdio. Add it to an MCP-capable agent and point
it at one collection with `KB_PATH`, or multiple named collections with
`KB_COLLECTIONS`. Existing configs can keep running bare `trace`; new configs
can use `trace serve` to make the server intent explicit. The MCP server name is
`trace`; tool prefixes are usually `mcp__trace__...`.

### Claude Code

```bash
claude mcp add trace \
  --transport stdio \
  --env KB_COLLECTIONS="docs:/path/to/docs,team-docs:/path/to/second-kb" \
  -- uv run --directory /path/to/trace trace serve
```

```bash
# Local inspector
KB_COLLECTIONS="docs:/path/to/docs,team-docs:/path/to/second-kb" \
uv run fastmcp dev src/trace_search/trace_server.py
```

## Configuration

| Variable                   | Description                                                     | Default            |
| -------------------------- | --------------------------------------------------------------- | ------------------ |
| `KB_PATH`                  | Path to a single collection (`~` is expanded)                   | —                  |
| `KB_COLLECTIONS`           | Comma-separated `name:path` pairs (`~` is expanded in paths)    | —                  |
| `INDEX_PATH`               | Root path for indexes (`~` is expanded)                         | —                  |
| `LOG_LEVEL`                | Logging level                                                   | `INFO`             |
| `EMBEDDING_MODEL`          | Embedding model (`all-MiniLM-L6-v2` or `BAAI/bge-base-en-v1.5`) | `all-MiniLM-L6-v2` |
| `EMBEDDING_BACKEND`        | Embedding runtime: `onnx` (int8, faster) or `torch`             | `onnx`             |
| `EMBEDDING_WARMUP_ENABLED` | Pre-encode at startup to reduce first-query latency             | `true`             |
| `RERANKER_ENABLED`         | Enable reranking                                                | `false`            |

`KB_COLLECTIONS` and `KB_PATH` are mutually exclusive — setting both raises a startup error.
Invalid paths, collection names, and log levels fail fast with clear startup errors.
Valid log levels are `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`, and `NOTSET`.

## Agent Tools

These map directly to the CLI commands above.

| Tool              | Description                                                            |
| ----------------- | ---------------------------------------------------------------------- |
| `search`          | Smart BM25-first search with semantic/hybrid fallback (default)        |
| `semantic_search` | Vector similarity search                                               |
| `keyword_search`  | Direct BM25 keyword search for exact terms                             |
| `search_hybrid`   | Semantic + keyword combined                                            |
| `get_document`    | Fetch a document by path                                               |
| `list_documents`  | List documents, optionally by folder                                   |
| `index_stats`     | Show index status                                                      |
| `doctor`          | Diagnose config, visible docs, exclusions, indexes, and sample queries |
| `reindex`         | Update indexes incrementally; pass `force=true` to rebuild from scratch |

In multi-collection mode, search and document tools accept an optional `collection` parameter.

Start with `search`. It runs BM25 first, falls back when results look weak,
reports the winning strategy, groups context by document, includes match
evidence, and suggests useful `get_document(path=...)` follow-ups.

Use `keyword_search`, `semantic_search`, or `search_hybrid` when you want a
specific retrieval mode for debugging, evaluation, or deterministic comparisons.

## Reindexing

`reindex` is incremental by default. Trace fingerprints each source file with a
SHA-256 hash plus mtime and size, so unchanged files are skipped — only added,
changed, and removed files are reprocessed. Run `trace reindex --force`
(`force=true` in MCP) to drop both indexes and rebuild every file from scratch
after a model change or to recover from corruption.

`doctor` reports the next-reindex plan and a categorized change summary:

```text
- Index status: stale
  - 1 added, 2 changed, 1 removed since last index.
  - Next `reindex` will run incrementally on changed files.
- Source changes since last index: unchanged=27, added=1, changed=2, removed=1
```

## Filtering Searches

All four search tools and `list_documents` accept three optional filters that
scope results before ranking:

```bash
# Only docs under architecture/, only Markdown, only files modified in 2026
trace search "router" \
  --path-prefix architecture/ \
  --extensions .md \
  --since 2026-01-01T00:00:00Z
```

| Parameter | CLI flag | Accepts |
| --- | --- | --- |
| `path_prefix` | `--path-prefix` (repeatable) | string or list — OR-matched against the start of the relative path |
| `extensions` | `--extensions` | list of `.md`/`.py`/...; comma-separated string also works |
| `since` | `--since` | ISO 8601 datetime; matches files with `mtime >= since` |

Filters combine with AND semantics and surface in `search` output under
`Active filters` so you can tell why a query came back empty.

## Troubleshooting

Run `trace doctor` when search returns nothing or setup feels suspicious:

```bash
KB_PATH=/path/to/your/docs uv run trace doctor "frontmatter"
KB_COLLECTIONS="docs:/path/to/docs,team:/path/to/team" uv run trace doctor --collection docs "onboarding"
```

When you include a sample query, `doctor` probes existing indexes only. It will
tell you to run `reindex` if indexes are missing instead of building them as a
side effect.

Doctor checks:

- whether `KB_PATH` / `KB_COLLECTIONS` is valid
- how many supported documents are visible by extension
- how many paths are excluded and why
- whether ChromaDB and BM25 indexes are missing, stale, incompatible, or unknown
- the index metadata schema version and whether the next `reindex` will be incremental or forced
- per-collection counts of unchanged, added, changed, and removed files since the last build
- last successful index time when metadata exists
- optional sample query latency and top-result summary

If doctor reports unknown metadata for an older index, run `reindex` once to populate model and freshness metadata. An older schema version (`v1`) will run as a forced rebuild on next reindex; subsequent runs are incremental.

## Index Storage

Indexes are stored under each collection in `.mcp-search/indexes/` by default.
If `INDEX_PATH` is set, single-collection mode stores indexes there;
multi-collection mode uses one subdirectory per collection.

## Development

```bash
# Checks
uv run python -m pytest -m "not slow"
uv run ruff check .
uv build

# Rebuild index
KB_PATH=/path/to/your/docs \
uv run python -c "from trace_search.indexer import WikiIndexer; WikiIndexer().build_index(force=True)"

# Search evaluation (optional): copy template, point KB_PATH at matching corpus
cp tools/eval/golden_queries.example.yaml tools/eval/golden_queries.yaml
KB_PATH=/path/to/your/docs uv run python -c "from trace_search.indexer import WikiIndexer; WikiIndexer().build_index(force=True)"
KB_PATH=/path/to/your/docs uv run python -m tools.eval.cli --quick

# Tiny committed fixture smoke test
KB_PATH=tests/fixtures/eval_kb EVAL_GOLDEN_QUERIES=tests/fixtures/eval_golden_queries.yaml \
  uv run python -m tools.eval.cli --full --search semantic
```
