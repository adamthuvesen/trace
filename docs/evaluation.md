# Evaluation

How to run the retrieval eval harness ([`tools/eval/`](../tools/eval/)). Committed
benchmark results live in [docs/benchmarks/](benchmarks/).

## Quickstart

```bash
# Tiny committed fixture (no copy step; good smoke test, runs the prod `smart` mode)
KB_PATH=tests/fixtures/eval_kb EVAL_GOLDEN_QUERIES=tests/fixtures/eval_golden_queries.yaml \
  uv run python -m tools.eval.cli --full --search smart
```

## Full wiki eval

Runs against your real KB plus a local `golden_queries.yaml`:

```bash
cp tools/eval/golden_queries.example.yaml tools/eval/golden_queries.yaml
KB_PATH=/path/to/your/docs uv run python -c "from trace_search import WikiIndexer; WikiIndexer().build_index(force=True)"
KB_PATH=/path/to/your/docs uv run python -m tools.eval --quick
KB_PATH=/path/to/your/docs uv run python -m tools.eval --full
```

## Committed fixture eval

The fixture under `tests/fixtures/eval_kb` needs no copy step. Swap `--search` to
compare modes (`bm25`, `semantic`, `hybrid`, `smart`); `smart` is the production
MCP default path:

```bash
KB_PATH=tests/fixtures/eval_kb EVAL_GOLDEN_QUERIES=tests/fixtures/eval_golden_queries.yaml \
  uv run python -m tools.eval.cli --full --search semantic
KB_PATH=tests/fixtures/eval_kb EVAL_GOLDEN_QUERIES=tests/fixtures/eval_golden_queries.yaml \
  uv run python -m tools.eval.cli --full --search smart
```

CI runs the same fixture eval as a separate, non-gating job
(`uv run python -m tools.eval.cli --ci --search smart`).

## Pytest path

The slow retrieval test reuses the same golden file:

```bash
uv run pytest tests/test_eval_retrieval.py -m slow
```
