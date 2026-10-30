# Trace

![License](https://img.shields.io/github/license/adamthuvesen/trace) ![Python](https://img.shields.io/badge/python-3.13%2B-blue)

Trace searches a local folder through a CLI or MCP server.
It returns ranked passages, source paths, and suggested document fetches.
Use it when an agent or a person needs evidence from files on disk.

Retrieval runs locally with ONNX embeddings.
Initial setup can download dependencies and models.
See [model prerequisites](docs/development.md#models-and-network-prerequisites) before disconnected use.

## Install and search

Trace needs Python 3.13+ and `uv`.
This example searches the committed fixture with a scratch index.

```bash
uv sync --locked
KB_PATH=tests/fixtures/eval_kb INDEX_PATH="$(mktemp -d)" \
  uv run --locked trace search "BM25 ranking" --top-k 2
```

The response includes the selected strategy, ranked document snippets, paths, and `get_document` follow-ups.
The default `search` uses BM25 when its leading document clearly wins.
Otherwise it combines BM25 and semantic rankings per document.
See [retrieval modes](docs/retrieval-modes.md) for the exact routing and ranking behavior.

Supported formats include Markdown, PDF, Word, PowerPoint, CSV, SQL, Python, YAML, TypeScript, and Jupyter notebooks.
The optional [converter](docs/development.md#document-conversion) creates a verified Markdown mirror.

## CLI

Use `uv run trace ...` in this checkout, or `trace ...` after package installation.
With no subcommand, `trace` starts the MCP server.

```bash
KB_PATH=/path/to/docs uv run --locked trace search "sample query"
KB_PATH=/path/to/docs uv run --locked trace doctor
KB_PATH=/path/to/docs uv run --locked trace reindex
KB_PATH=/path/to/docs uv run --locked trace serve
```

| Command | Behavior |
| --- | --- |
| `search "query"` | Adaptive BM25 and semantic retrieval |
| `semantic-search "query"` | Vector similarity with lexical ranking evidence |
| `keyword-search "term"` | Direct BM25 retrieval |
| `hybrid-search "query"` | BM25 and semantic fusion per document |
| `get-document path/to/doc.md` | Read a current source document |
| `list-documents` | Scan visible current files |
| `index-stats` | Show index status |
| `doctor "sample query"` | Diagnose configuration, visibility, and existing indexes |
| `reindex` | Incremental update, or complete rebuild with `--force` |
| `serve` | MCP over stdio, or HTTP with `--transport http` |

Search commands accept `--top-k`.
`keyword-search` uses `--max-results`.
Search commands and `list-documents` accept repeated `--path-prefix`, comma-separated `--extensions`, and ISO 8601 `--since`.
Filters combine with AND.
`list-documents` also accepts `--folder` and `--limit`.

For named collections, replace `KB_PATH` with `KB_COLLECTIONS`.
Use `--collection` to select one collection.

```bash
KB_COLLECTIONS="docs:/path/to/docs,team:/path/to/team" \
  uv run --locked trace search "sample query" --collection docs
```

Failures return a nonzero exit status.
CLI errors appear on stderr.
MCP failures use the tool error flag.
A search with no matches is a successful empty result.

## MCP

The default transport is stdio.
The server exposes `search`, `semantic_search`, `keyword_search`, `search_hybrid`, `get_document`, `list_documents`, `index_stats`, `doctor`, and `reindex`.
Search and listing tools accept the same scope filters as the CLI.
Multi-collection tools also accept `collection`.

For Claude Code:

```bash
claude mcp add trace --transport stdio \
  --env KB_PATH=/path/to/docs \
  -- uv run --directory /path/to/trace trace serve
```

For one shared loopback server:

```bash
KB_PATH=/path/to/docs uv run --locked trace serve \
  --transport http --host 127.0.0.1 --port 7421
```

Clients connect to `http://127.0.0.1:7421/mcp`.
The server is stateless and unauthenticated.
It restricts the listener to loopback and protects requests through host and origin checks.
The [development guide](docs/development.md#mcp-inspector) documents the FastMCP inspector factory.

## Configuration and indexes

| Variable | Default | Purpose |
| --- | --- | --- |
| `KB_PATH` | unset | One knowledge base |
| `KB_COLLECTIONS` | unset | Comma-separated `name:path` collections |
| `INDEX_PATH` | KB-local `.mcp-search/indexes/` | Index storage root |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Default model, or `BAAI/bge-base-en-v1.5` |
| `TRACE_MODEL_CACHE` | XDG cache or `~/.cache/trace/models` | Durable model storage |
| `LOG_LEVEL` | `INFO` | Python logging level |

`KB_PATH` and `KB_COLLECTIONS` are mutually exclusive.
Invalid paths, duplicate collection names, and invalid settings fail during configuration.
In multi-collection mode, `INDEX_PATH` contains one directory per collection.

Frontmatter `title`, `aliases`, and `summary` contribute to retrieval.
Other YAML keys stay outside ranking text.
`status: superseded` and `status: deprecated` demote replaced pages.
A KB-root `.traceignore` supports gitignore patterns and negation.
Trace also skips hidden paths and configured excluded directories within the KB.

Reindexing publishes a complete immutable generation and swaps `CURRENT` atomically.
Running readers notice the generation on a later request.
Searches retain one generation per collection through ranking and neighbor lookup.
`get-document` reads the current source file, so it can contain newer text.
See [index compatibility](docs/architecture.md#index-compatibility) for the v6 to v7 migration and build recipe rules.

## Development and evaluation

```bash
just bootstrap
just check
just eval
just stress
just verify
```

`just eval` checks all 17 core queries against a committed quality baseline.
`just stress` checks a separate 12-query population.
Both use scratch indexes regardless of `INDEX_PATH`.
The fixtures test public retrieval behavior on a small corpus.
They do not establish corpus-scale performance.

Read [development](docs/development.md) for commands and check coverage.
Read [evaluation](docs/evaluation.md) for metrics, manifests, baseline migration, and private query sets.
Read [architecture](docs/architecture.md) for module ownership and compatibility boundaries.

## Historical benchmark results

These results come from committed reports dated 2026-06-13.
They describe those historical runs, including their original timing protocol.
Current fixture gates use separately recorded baselines.

| Mode and source | Top-1 | Top-5 | MRR | p50 ms | p95 ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| [bm25](docs/benchmarks/eval_bm25.json) | 88.2% | 94.1% | 0.912 | 0.16 | 2.64 |
| [semantic](docs/benchmarks/eval_semantic.json) | 88.2% | 100.0% | 0.941 | 6.71 | 7.14 |
| [hybrid](docs/benchmarks/eval_hybrid.json) | 88.2% | 100.0% | 0.941 | 7.10 | 10.87 |
| [adaptive](docs/benchmarks/eval_adaptive.json) | 88.2% | 100.0% | 0.941 | 7.20 | 10.56 |

[Benchmark notes](docs/benchmarks/README.md) explain the historical artifacts.
The [2026-09-29 investigation](docs/benchmarks/2026-09-29-trace-overhaul.md) covers later experiments and their limits.
