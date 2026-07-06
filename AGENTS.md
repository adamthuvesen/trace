# AGENTS.md

Instructions for AI agents working in this repo. Human docs: [README.md](README.md)

User-level guidance (tone, principles, git etiquette) lives in `~/.claude/CLAUDE.md`
and `~/dotfiles/agents/AGENTS.md` and is *not* repeated here. This file is for
project-specific facts.

## Project Overview

Trace is an MCP server for semantic, keyword, and hybrid search over a local
knowledge base.

## Before You Start

Use these entry points first:

- Default entrypoint: `uv run trace`
- Local inspector: `KB_PATH=/path/to/your/docs uv run fastmcp dev src/trace_search/server/trace_server.py`
- Package layout (`src/trace_search/`): [`config.py`](src/trace_search/config.py) at
  root; subpackages [`extraction/`](src/trace_search/extraction/) (extractors,
  chunking, corpus), [`indexing/`](src/trace_search/indexing/) (embeddings,
  kb_paths, index_paths, index_metadata, wiki_indexer),
  [`retrieval/`](src/trace_search/retrieval/) (search, bm25_tokenize,
  query_profile, search_types, hit_builders, formatting, models),
  [`collections/`](src/trace_search/collections/) (collection_registry,
  operations, diagnostics), [`server/`](src/trace_search/server/) (trace_server,
  cli, mcp_tools, server_warmup)
- Keep the public import surface flat via
  [`trace_search/__init__.py`](src/trace_search/__init__.py) re-exports
  (`WikiIndexer`, `AdaptiveSearch`, `CollectionRegistry`, `format_results`, …)
- Indexes live under the KB root unless `INDEX_PATH` is set
- `reindex` is incremental by default (skips unchanged files); pass `--force` / `force=true` to rebuild from scratch
- All search tools and `list_documents` accept `path_prefix`, `extensions`, and `since` filters

## Read The Matching Doc First

Before editing a subsystem, read the matching doc:

- **Retrieval modes (bm25/semantic/hybrid/adaptive)**: [docs/retrieval-modes.md](docs/retrieval-modes.md)
- **Running the eval harness**: [docs/evaluation.md](docs/evaluation.md)
- **Eval / benchmark results**: [docs/benchmarks/](docs/benchmarks/)

`adaptive` is the production MCP default: BM25-first, with semantic/hybrid fallback.
See [`retrieval/search.py`](src/trace_search/retrieval/search.py) and
[`retrieval/bm25_tokenize.py`](src/trace_search/retrieval/bm25_tokenize.py).

If a doc disagrees with code, fix the doc in the same change.

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

# Lint + format (CI enforces both)
uv run ruff check .
uv run ruff format --check .

# Evaluation: smoke test against the committed fixture (full guide: docs/evaluation.md)
KB_PATH=tests/fixtures/eval_kb EVAL_GOLDEN_QUERIES=tests/fixtures/eval_golden_queries.yaml \
  uv run python -m tools.eval.cli --full --search adaptive

# Module size guard (no file > 1000 lines)
uv run python scripts/check_module_sizes.py
```
