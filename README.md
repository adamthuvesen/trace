# Trace

Local MCP server for searching document collections — keyword, semantic, and hybrid search over files on disk.

Supports: Markdown, PDF, Word, PowerPoint, CSV, SQL, Python, YAML, TypeScript, Jupyter notebooks.

## Install

Requires Python 3.11+ and `uv`.

```bash
uv sync
```

## Run

```bash
# Multi-collection
KB_COLLECTIONS="docs:/path/to/docs,team-docs:/path/to/second-kb" uv run trace

# Single collection
KB_PATH=/path/to/your/docs uv run trace

# Diagnose setup before starting or from a shell
KB_PATH=/path/to/your/docs uv run trace doctor
KB_PATH=/path/to/your/docs uv run trace doctor "sample query"

# Local inspector
KB_COLLECTIONS="docs:/path/to/docs,team-docs:/path/to/second-kb" \
uv run fastmcp dev src/trace_search/trace_server.py
```

## Claude Code

```bash
claude mcp add trace \
  --transport stdio \
  --env KB_COLLECTIONS="docs:/path/to/docs,team-docs:/path/to/second-kb" \
  -- uv run --directory /path/to/trace trace
```

## Configuration

| Variable | Description | Default |
|---|---|---|
| `KB_PATH` | Path to a single collection | — |
| `KB_COLLECTIONS` | Comma-separated `name:path` pairs | — |
| `INDEX_PATH` | Root path for indexes | — |
| `LOG_LEVEL` | Logging level | `INFO` |
| `EMBEDDING_MODEL` | Embedding model (`all-MiniLM-L6-v2` or `BAAI/bge-base-en-v1.5`) | `all-MiniLM-L6-v2` |
| `EMBEDDING_BACKEND` | Embedding runtime: `onnx` (int8, faster) or `torch` | `onnx` |
| `EMBEDDING_WARMUP_ENABLED` | Pre-encode at startup to reduce first-query latency | `true` |
| `RERANKER_ENABLED` | Enable reranking | `false` |

`KB_COLLECTIONS` and `KB_PATH` are mutually exclusive — setting both raises a startup error.

## Tools

| Tool | Description |
|---|---|
| `search` | Smart BM25-first search with semantic/hybrid fallback (default) |
| `semantic_search` | Vector similarity search |
| `keyword_search` | Direct BM25 keyword search for exact terms |
| `search_hybrid` | Semantic + keyword combined |
| `get_document` | Fetch a document by path |
| `list_documents` | List documents, optionally by folder |
| `index_stats` | Show index status |
| `doctor` | Diagnose config, visible docs, exclusions, indexes, and sample queries |
| `reindex` | Rebuild indexes |

In multi-collection mode, search and document tools accept an optional `collection` parameter.

Start with `search`. It runs BM25 first, falls back when results look weak, reports the winning strategy, groups context by document, includes match evidence, and suggests useful `get_document(path=...)` follow-ups.

Use `keyword_search`, `semantic_search`, or `search_hybrid` when you want a specific retrieval mode for debugging, evaluation, or deterministic comparisons.

## Troubleshooting

Run `trace doctor` when search returns nothing or setup feels suspicious:

```bash
KB_PATH=/path/to/your/docs uv run trace doctor "frontmatter"
KB_COLLECTIONS="docs:/path/to/docs,team:/path/to/team" uv run trace doctor --collection docs "onboarding"
```

Doctor checks:

- whether `KB_PATH` / `KB_COLLECTIONS` is valid
- how many supported documents are visible by extension
- how many paths are excluded and why
- whether ChromaDB and BM25 indexes are missing, stale, incompatible, or unknown
- last successful index time when metadata exists
- optional sample query latency and top-result summary

If doctor reports unknown metadata for an older index, run `reindex` once to populate model and freshness metadata.

## Index Storage

Indexes are stored under each collection in `.mcp-search/indexes/` by default. If `INDEX_PATH` is set, single-collection mode stores indexes there; multi-collection mode uses one subdirectory per collection.

## Development

```bash
# Tests
uv run python -m pytest -m "not slow"

# Rebuild index
KB_PATH=/path/to/your/docs \
uv run python -c "from trace_search.indexer import WikiIndexer; WikiIndexer().build_index(force=True)"

# Search evaluation (optional): copy template, point KB_PATH at matching corpus
cp tools/eval/golden_queries.example.yaml tools/eval/golden_queries.yaml
KB_PATH=/path/to/your/docs uv run python -c "from trace_search.indexer import WikiIndexer; WikiIndexer().build_index(force=True)"
KB_PATH=/path/to/your/docs uv run python -m tools.eval.cli --quick
```

## Notes

- MCP server name is `trace` — tool prefixes: `mcp__trace__search`
