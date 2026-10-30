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
Use `just full` for fast checks, model checks, packaging, and both battle suites.
Prove changes with `just verify` (`verify-trace` skill at `.agents/skills/verify-trace/`).
See [development.md](docs/development.md) for prerequisites and check coverage.

## Choose the owner before editing

| Change | Read first | Implementation owner |
| --- | --- | --- |
| Application behavior, CLI, MCP | [architecture.md](docs/architecture.md) | `collections/operations.py`, then adapter |
| Ranking, hit identity, formatting | [retrieval-modes.md](docs/retrieval-modes.md) | `retrieval/search.py`, `search_types.py`, `formatting.py` |
| Source capture, builds, generations | [architecture.md](docs/architecture.md#index-lifecycle) | `indexing/index_builder.py`, `index_reader.py`, `index_store.py` |
| Query sets, metrics, baselines | [evaluation.md](docs/evaluation.md) | `tools/eval/` |
| Document conversion | [development.md](docs/development.md#document-conversion) | `tools/convert_to_markdown.py` |

Composed application behavior belongs in `TraceOperations`; CLI and MCP adapters stay thin.

## Enforced Rules

| Rule | Enforced by | Added |
| --- | --- | --- |
| Runtime code does not import `server/`; indexing does not import retrieval or collections | `pyproject.toml::tool.importlinter` | 2026-11-04 |
| Runtime and tooling code type-checks strictly | `pyproject.toml::tool.basedpyright`, `justfile::ratchet` | 2026-11-04 |
| Chunk text or metadata changes bump `INDEX_METADATA_VERSION` | `tests/test_chunk_transform_golden.py::test_chunk_transform_changes_bump_index_metadata_version` | 2026-11-06 |
| MCP output text stays stable | `tests/test_mcp_output_golden.py::test_mcp_output_matches_golden` | 2026-11-06 |
| MCP tool names stay stable | `tests/test_transports.py::test_fastmcp_inspector_loads_noarg_factory` | 2026-11-04 |
| Unregistered pytest markers fail; `transport` tests run only in `just integration` | `pyproject.toml::strict_markers`, `justfile::integration` | 2026-11-06 |
| `KB_COLLECTIONS` format stays stable | `tests/test_multi_collection.py::TestKBCollectionsParsing` | 2026-11-04 |
| Filesystem ownership and failed publication keep the last complete index | `tests/test_runtime_boundaries.py` | 2026-11-04 |
| Committed benchmark artifacts hold no local home paths | `tests/test_eval_contracts.py::test_committed_benchmark_artifacts_contain_no_absolute_home_paths` | 2026-11-06 |
| Fixture quality holds its committed baselines within tolerance | `justfile::eval`, `justfile::stress`, `tools/eval/regression.py::TOP_1_DROP_TOLERANCE` | 2026-11-04 |
| Multi-KB quality holds per-mode baselines | `justfile::battle`, `justfile::battle-challenge` | 2026-11-04 |
| The installed wheel exposes the public API | `tools/verify_package.py` | 2026-11-04 |
| `just verify control` must observe FAIL before a verify pass counts | `.agents/skills/verify-trace/drives.py::control` | 2026-11-06 |
| Every path cited in this table exists | `tests/test_agents_rules.py::test_enforced_rules_cite_real_files` | 2026-11-06 |

`just check` runs the import contracts, types, and the fast tests above.
`just integration` runs slow and transport tests, the baselines, battle suites, and wheel check.

## Index and evaluation traps

- Run manual experiments with a scratch `INDEX_PATH`. Evaluation CLIs create their own scratch indexes.
- Read the [migration contract](docs/architecture.md#index-compatibility) before changing persisted schemas or backend identity.
- Keep private query text out of committed benchmark artifacts. The path check cannot detect it.

## Entrypoints

```bash
KB_PATH=/path/to/docs uv run --locked trace
KB_PATH=/path/to/docs uv run --locked fastmcp dev inspector src/trace_search/server/trace_server.py:create_mcp
```

Use the `create_mcp` factory with the pinned FastMCP inspector.
`uv run trace` without a subcommand starts the MCP server.
