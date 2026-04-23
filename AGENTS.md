# AGENTS.md

Instructions for AI agents. Human docs: [README.md](README.md)

## Project Overview

Trace is an MCP server for semantic, keyword, and hybrid search over a local knowledge base.

## Before You Start

Start here:

- Default entrypoint: `uv run trace`
- Local inspector: `KB_PATH=/path/to/your/docs uv run fastmcp dev src/trace_search/trace_server.py`
- Core files: `config.py`, `server_app.py`, `trace_server.py`, `search.py`, `indexer.py`
- Indexes live under the KB root unless `INDEX_PATH` is set

## Commands

```bash
# Setup
uv sync

# Run server
uv run trace

# Dev mode (FastMCP inspector)
KB_PATH=/path/to/your/docs uv run fastmcp dev src/trace_search/trace_server.py

# Tests
KB_PATH=/path/to/your/docs uv run python -m pytest tests/ -v
uv run python -m pytest -m "not slow"          # skip embedding tests

# Evaluation — full wiki (local golden_queries.yaml + KB_PATH)
cp tools/eval/golden_queries.example.yaml tools/eval/golden_queries.yaml
KB_PATH=/path/to/your/docs uv run python -c "from trace_search.indexer import WikiIndexer; WikiIndexer().build_index(force=True)"
KB_PATH=/path/to/your/docs uv run python -m tools.eval --quick
KB_PATH=/path/to/your/docs uv run python -m tools.eval --full

# Evaluation — tiny committed fixture (no copy step; good smoke test)
KB_PATH=tests/fixtures/eval_kb EVAL_GOLDEN_QUERIES=tests/fixtures/eval_golden_queries.yaml \
  uv run python -m tools.eval.cli --full --search semantic
# Optional: pytest uses the same golden file — uv run pytest tests/test_eval_retrieval.py -m slow
```
