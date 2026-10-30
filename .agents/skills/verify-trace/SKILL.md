---
name: verify-trace
description: "Drives Trace's real CLI, MCP server, and built wheel against temp fixture collections. Use to run, launch, drive, or verify trace, or to prove a change to it works."
---

# Verify Trace

`just check` proves the code is consistent. This skill proves the behavior. It builds two fresh collections, `docs` (a copy of `tests/fixtures/eval_kb`) and `notes` (three inline files). Then it drives the real `trace` console, `trace serve` over stdio and HTTP, and an installed wheel.

## Run

- `just verify` after a change. It runs the drives whose paths match files changed against `main`, plus uncommitted and untracked files. When nothing matches, it runs the `search` smoke drive.
- `just verify all` before you hand over larger work. The CLI and MCP drives take about 7 seconds. The `package` drive runs at the same time on its own thread and sets the wall time, about 25 to 35 seconds.
- `just verify list` shows each drive, what it proves, and the paths it covers.
- `just verify <drive> ...` runs only the named drives.
- `just verify control` drives `search` and expects the wrong top hit for a keyword query. It exits 0 only when it observes FAIL.

The helper is `.agents/skills/verify-trace/verify`. It runs itself under `uv run --locked --extra convert` when started outside the project venv.

## Reading results

- Each drive prints `PASS|FAIL <drive> <seconds>s <detail>`. A FAIL detail names the expected and the actual top hit, exit code, or count.
- Evidence is in `.verify/runs/<utc>-<sha7>[-dirty]/`. It holds `summary.json` and `env.json`. Each drive has a directory with one file per command (command, exit code, stdout, stderr) and the server logs.
- The helper never retries. Any failure is a FAIL. There is no FLAKY result.

## Isolation

- Children get a temp HOME and temp XDG directories, `KB_COLLECTIONS` and `INDEX_PATH` in the scratch directory, and a cwd outside the repo. The cwd matters because `Settings` reads `.env` from it.
- Embeddings are local ONNX models. The helper copies the cached model into the scratch directory and sets `HF_HUB_OFFLINE=1`. Nothing downloads, and the real cache is never written.
- A `sitecustomize` audit hook (the same hook as `tests/test_transports.py`) refuses every non-loopback connection and logs it. A drive fails when that log is not empty.
- Each drive runs its subprocesses in their own process group and stops that group when the drive ends.

## Limits

- Retrieval quality is not measured here. Use `just eval`, `just stress`, and the battle suites.
- A machine without the cached model fails preflight. Run `just integration` once to download the model.

## Gotchas

- Keyword search abstains on weak hits: `max(1.0, 0.72 * ln(chunks))` with no filter active. In a tiny collection, a term that appears once is dropped, and adaptive `search` then returns nothing for a keyword-like query. Use the `eval_kb` copy for keyword checks, or pass a filter such as `--path-prefix`.
- `trace doctor` exits 1 while the index is stale, which is the case after any source edit.
- Adaptive `search INDEX_PATH` uses hybrid ranking ("BM25 matched only one document"). Assert the top hit, not the strategy.
