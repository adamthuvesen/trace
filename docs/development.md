# Development

Use Python 3.14 or newer, `uv`, and `just`.
The repository defaults to Python 3.14 through `.python-version`.

Minimal Linux installations can require a C compiler when PyStemmer has no wheel for the platform.
For Debian or Ubuntu, install `build-essential` before `just bootstrap`.

```bash
just bootstrap
just check
just test-file tests/test_eval_contracts.py
just eval
```

`just bootstrap` installs locked development and conversion dependencies.
`just check` runs lint, formatting, strict typing, import contracts, and tests without the `slow` or `transport` marker.
The type check covers `src/trace_search` and `tools`.

## Verification commands

| Command | Coverage | Limits |
| --- | --- | --- |
| `just fix` | Apply ruff fixes and formatting | Run before `check` |
| `just check` | Static checks and fast tests | Excludes tests marked `slow` or `transport` |
| `just test-file tests/test_eval_contracts.py` | One file or pytest node | Scope depends on the supplied path |
| `just eval` | All 17 core fixture queries and committed quality baseline | Small public corpus |
| `just stress` | Separate 12-query stress population and its baseline | Same public corpus |
| `just battle` | Comparative gates for all standard battle KBs and modes | Committed public fixtures |
| `just battle-challenge` | Comparative gates for the separate challenge populations | Committed public fixtures |
| `just package` | Fresh wheel environment, public imports, typing marker, CLI, stdio MCP, external type consumers | Package fixture checks do not measure retrieval quality |
| `just integration` | Slow model tests, real stdio and HTTP transport tests, package verification, both fixture gates, both comparative battle gates | Requires model preparation |
| `just slow` | `check` followed by `integration` | Runs on the current host and interpreter |
| `just verify` | Drives the real CLI, MCP server, and wheel (`verify-trace` skill) | Needs the cached embedding model |

CI uses these recipes in [.github/workflows/ci.yml](../.github/workflows/ci.yml).
Its fast-check matrix configures Ubuntu with Python 3.14 and macOS with Python 3.14.
The model, package, and retrieval job configures Ubuntu with Python 3.14.
A successful local run verifies its local environment.
CI matrix coverage requires successful runs of those jobs.

## Models and network prerequisites

Retrieval embeds documents and queries locally through ONNX.
Initial environment installation and model preparation can require network access.
Prepare the model cache before disconnected use.
A persisted search index alone does not supply the query embedding model.

Models use `TRACE_MODEL_CACHE` when set.
Otherwise they use `$XDG_CACHE_HOME/trace/models` or `~/.cache/trace/models`.
Use a durable directory because temporary directories can lose model files.

```bash
TRACE_MODEL_CACHE=/persistent/trace-models just eval
```

That command prepares and tests the default model through a scratch index.
For the first verification run, use `just eval` to cache the model, then run `just verify search`.
If you set `TRACE_MODEL_CACHE` or `XDG_CACHE_HOME`, keep it set for both commands.
Check disconnected behavior in the target environment after preparing dependencies and models.
Model resolution can depend on the embedding runtime and its cache state.

## MCP inspector

```bash
KB_PATH=tests/fixtures/eval_kb uv run --locked fastmcp dev inspector src/trace_search/server/trace_server.py:create_mcp
```

The pinned FastMCP version uses `dev inspector` and a factory server specification.
The factory configures the same tools as `trace serve`.

Trace pins FastMCP 4.1.6.
Transport tests cover automatic negotiation, MCP `2025-11-25`, and MCP `2026-07-28` over stdio and HTTP.
HTTP tests keep the same client connected across a server restart.

## Document conversion

The converter creates a Markdown mirror from PDF, Word, PowerPoint, CSV, Excel, Markdown, or text files.
Use distinct source and output directories.

```bash
uv run --locked --extra convert python tools/convert_to_markdown.py \
  --source-path /path/to/source --output-dir /path/to/markdown --dry-run
uv run --locked --extra convert python tools/convert_to_markdown.py \
  --source-path /path/to/source --output-dir /path/to/markdown
```

Planning validates every destination before conversion starts.
It rejects destination collisions, overlapping roots, and paths that escape the allowed root through symlinks.
CSV parsing rejects malformed rows.
A conversion failure returns a nonzero status.

Each output has a hidden `.<output-name>.trace-conversion.json` sidecar.
The sidecar records the converter version, source identity, source hash, and output hash.
A verified unchanged output can be reused.
Changed sources are converted again.

Existing outputs without matching provenance are `unverified`.
The converter reports them and returns a nonzero status.
Inspect those files, then use `--force` to regenerate them and establish provenance.
A conversion publishes each output and sidecar separately from other files.
The whole conversion batch is not a transaction.

## Making a change

Read the subsystem document linked from [AGENTS.md](../AGENTS.md).
Pass `SearchHit` and `SearchResponse` between modules. Only `retrieval/formatting.py` turns them into output text.
The [architecture guide](architecture.md) identifies each owner.

Run the relevant focused test while changing behavior.
Then use `just check` and the integration recipe affected by the change.
Use the [evaluation guide](evaluation.md) before modifying metrics or baselines.

Text and code sources must use valid UTF-8.
Unreadable visible directories and malformed source text stop a build and preserve the last complete index.
Correct the source or exclude it explicitly before retrying.
