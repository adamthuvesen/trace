# AGENTS.md

Project instructions for Trace. Human entrypoint: [README.md](README.md).
The nearest project instructions override user-level defaults.

## Start here

```bash
just bootstrap
just check
just test-file tests/test_eval_contracts.py
```

Use `just fix` to apply the lint and format fixers.

Use `just eval` for the complete core fixture and `just stress` for the separate stress fixture.
Use `just slow` for fast checks, model checks, packaging, and both battle suites.
Prove changes with `just verify` (`verify-trace` skill at `.agents/skills/verify-trace/`).
See [development.md](docs/development.md) for prerequisites and check coverage.

## Choose the owner before editing

| Change | Read first | Implementation owner |
| --- | --- |
| Application behavior, CLI, MCP | [architecture.md](docs/architecture.md) | `collections/operations.py`, then adapter |
| Ranking, hit identity, formatting | [retrieval-modes.md](docs/retrieval-modes.md) | `retrieval/search.py`, `search_types.py`, `formatting.py` |
| Source capture, builds, generations | [architecture.md](docs/architecture.md#index-lifecycle) | `indexing/index_builder.py`, `index_reader.py`, `index_store.py` |
| Query sets, metrics, baselines | [evaluation.md](docs/evaluation.md) | `tools/eval/` |

Composed application behavior belongs in `TraceOperations`; CLI and MCP adapters stay thin.

## Enforced Rules

`just check` runs the import contracts, types, and the fast tests above.
`just integration` runs slow and transport tests, the baselines, battle suites, and wheel check.

| Rule | Enforced by |
| --- | --- |
| Runtime code does not import `server/`; indexing does not import retrieval or collections | `pyproject.toml::tool.importlinter` |
| Extraction does not import indexing; `server/` reaches runtime code only through `collections.operations`, `collections.errors`, `collections.diagnostics`, and `config` | `pyproject.toml::tool.importlinter` |
| Process calls, network clients, and paid SDKs stay in the owner files listed in `pyproject.toml` per-file-ignores | `pyproject.toml::tool.ruff.lint.flake8-tidy-imports.banned-api`, `tests/test_banned_api_owners.py::test_only_named_owners_ignore_tid251` |
| Chunk text or metadata changes bump `INDEX_METADATA_VERSION` | `tests/test_chunk_transform_golden.py::test_chunk_transform_changes_bump_index_metadata_version` |
| MCP output text stays stable | `tests/test_mcp_output_golden.py::test_mcp_output_matches_golden` |
| MCP tool names stay stable | `tests/test_transports.py::test_fastmcp_inspector_loads_noarg_factory` |
| Unregistered pytest markers fail; `transport` tests run only in `just integration` | `pyproject.toml::strict_markers`, `justfile::integration` |
| `KB_COLLECTIONS` format stays stable | `tests/test_multi_collection.py::TestKBCollectionsParsing` |
| Filesystem ownership and failed publication keep the last complete index | `tests/test_runtime_boundaries.py::test_unreadable_visible_subtree_aborts_build_and_retry_retains_documents`, `tests/test_runtime_boundaries.py::test_writer_lock_cannot_truncate_linked_source` |
| Committed benchmark artifacts hold no local home paths | `tests/test_eval_contracts.py::test_committed_benchmark_artifacts_contain_no_absolute_home_paths`, `tests/test_eval_contracts.py::test_home_path_scan_finds_a_planted_leak` |
| Fixture quality holds its committed baselines within tolerance | `justfile::eval`, `justfile::stress`, `tools/eval/regression.py::TOP_1_DROP_TOLERANCE` |
| Multi-KB quality holds per-mode baselines | `justfile::battle`, `justfile::battle-challenge` |
| The installed wheel exposes the public API | `tools/verify_package.py::verify_package` |
| `just verify control` must observe FAIL before a verify pass counts | `.agents/skills/verify-trace/drives.py::control` |
| A verify run fails when it changes the checkout, ignored paths and git state included | `.agents/skills/verify-trace/verify::checkout_changes` |
| Every skip, xfail, and unittest skip in the repo gives a reason | `tests/test_strict_mode.py::test_every_skip_gives_a_reason` |

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
