# AGENTS.md

Project instructions for Trace. Human entrypoint: [README.md](README.md).
The nearest project instructions override user-level defaults.

## Start here

```bash
just bootstrap
just check
just test-file tests/test_eval_contracts.py
```

Use `just eval` for the complete core fixture and `just stress` for the separate stress fixture.
Use `just verify` for fast checks, model checks, packaging, and both battle suites.
See [development.md](docs/development.md) for prerequisites and check coverage.

## Choose the owner before editing

| Change | Read first | Implementation owner |
| --- | --- | --- |
| Application behavior, CLI, MCP | [architecture.md](docs/architecture.md) | `collections/operations.py`, then adapter |
| Ranking, hit identity, formatting | [retrieval-modes.md](docs/retrieval-modes.md) | `retrieval/search.py`, `search_types.py`, `formatting.py` |
| Source capture, builds, generations | [architecture.md](docs/architecture.md#index-lifecycle) | `indexing/index_builder.py`, `index_reader.py`, `index_store.py` |
| Query sets, metrics, baselines | [evaluation.md](docs/evaluation.md) | `tools/eval/` |
| Document conversion | [development.md](docs/development.md#document-conversion) | `tools/convert_to_markdown.py` |

`WikiIndexer` and `CollectionRegistry` retain public compatibility methods.
New composed application behavior belongs in `TraceOperations`.
Keep public imports available through `trace_search/__init__.py`.
The following checks define the enforced boundaries.

| Boundary | Check |
| --- | --- |
| Runtime dependency direction | `lint-imports`, contracts in `pyproject.toml` |
| Runtime and tooling types | Strict `mypy` over `src/trace_search` and `tools` |
| Fixture quality populations | `just eval` and `just stress`, explicit manifest-bearing baselines |
| Multi-KB quality regression | `just battle` and `just battle-challenge`, observed per-mode baselines |
| Filesystem ownership and failed publication | `tests/test_runtime_boundaries.py`, actual filesystem and process cases |
| Installed public API | `just package`, isolated wheel and consumer checks |

## Index and evaluation traps

- Run manual experiments with a scratch `INDEX_PATH`. Evaluation CLIs create their own scratch indexes.
- Bump `INDEX_METADATA_VERSION` when transformed chunk text or metadata changes.
  Incremental indexing otherwise reuses existing chunks.
- Read the [migration contract](docs/architecture.md#index-compatibility) before changing persisted schemas or backend identity.
- Update the matching document when code changes invalidate its description.
- Keep private query text and private paths out of committed benchmark artifacts.

## Entrypoints

```bash
KB_PATH=/path/to/docs uv run --locked trace
KB_PATH=/path/to/docs uv run --locked fastmcp dev inspector src/trace_search/server/trace_server.py:create_mcp
```

Use the `create_mcp` factory with the pinned FastMCP inspector.
`uv run trace` without a subcommand starts the MCP server.
