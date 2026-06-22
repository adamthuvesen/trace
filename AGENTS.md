# AGENTS.md

Instructions for AI agents. Human docs: [README.md](README.md)

## Project Overview

Trace is an MCP server for semantic, keyword, and hybrid search over a local knowledge base.

## Before You Start

Start here:

- Default entrypoint: `uv run trace`
- Local inspector: `KB_PATH=/path/to/your/docs uv run fastmcp dev src/trace_search/server/trace_server.py`
- Package layout (`src/trace_search/`): `config.py` at root; subpackages
  `extraction/` (extractors, chunking, corpus), `indexing/` (embeddings,
  kb_paths, index_paths, index_metadata, wiki_indexer), `retrieval/` (search,
  bm25_tokenize, query_profile, search_types, hit_builders, formatting, models),
  `collections/` (collection_registry, operations, diagnostics), `server/`
  (trace_server, cli, mcp_tools, server_warmup)
- Public import surface stays flat via `trace_search/__init__.py` re-exports
  (`WikiIndexer`, `SmartSearch`, `CollectionRegistry`, `format_results`, …)
- Indexes live under the KB root unless `INDEX_PATH` is set
- `reindex` is incremental by default (skips unchanged files); pass `--force` / `force=true` to rebuild from scratch
- All search tools and `list_documents` accept `path_prefix`, `extensions`, and `since` filters

## Commands

```bash
# Setup
uv sync

# Run server
uv run trace

# Dev mode (FastMCP inspector)
KB_PATH=/path/to/your/docs uv run fastmcp dev src/trace_search/server/trace_server.py

# Tests
KB_PATH=/path/to/your/docs uv run python -m pytest tests/ -v
uv run python -m pytest -m "not slow"          # skip embedding tests

# Evaluation — full wiki (local golden_queries.yaml + KB_PATH)
cp tools/eval/golden_queries.example.yaml tools/eval/golden_queries.yaml
KB_PATH=/path/to/your/docs uv run python -c "from trace_search import WikiIndexer; WikiIndexer().build_index(force=True)"
KB_PATH=/path/to/your/docs uv run python -m tools.eval --quick
KB_PATH=/path/to/your/docs uv run python -m tools.eval --full

# Evaluation — tiny committed fixture (no copy step; good smoke test)
KB_PATH=tests/fixtures/eval_kb EVAL_GOLDEN_QUERIES=tests/fixtures/eval_golden_queries.yaml \
  uv run python -m tools.eval.cli --full --search semantic
# Production MCP default path:
KB_PATH=tests/fixtures/eval_kb EVAL_GOLDEN_QUERIES=tests/fixtures/eval_golden_queries.yaml \
  uv run python -m tools.eval.cli --full --search smart
# Optional: pytest uses the same golden file — uv run pytest tests/test_eval_retrieval.py -m slow

# Module size guard (no file > 1000 lines)
uv run python scripts/check_module_sizes.py
```
