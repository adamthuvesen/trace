set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

# Install the locked development environment.
bootstrap:
    uv sync --locked --dev

# Run the same fast checks locally and in CI.
check:
    uv run --locked ruff check . .agents/skills/verify-trace/verify
    uv run --locked ruff format --check . .agents/skills/verify-trace/verify
    uv run --locked basedpyright
    uv run --locked basedpyright --project .agents/skills/verify-trace
    uv run --locked lint-imports --no-logo
    uv run --locked python -m pytest -m "not slow and not transport" -q -n auto

# Apply every auto-fixer.
fix:
    uv run --locked ruff check --fix . .agents/skills/verify-trace/verify
    uv run --locked ruff format . .agents/skills/verify-trace/verify

# Run one test file or pytest node.
test-file path:
    uv run --locked python -m pytest {{quote(path)}} -q

# Evaluate every core fixture query against the committed baseline.
eval:
    KB_PATH=tests/fixtures/eval_kb EVAL_GOLDEN_QUERIES=tests/fixtures/eval_golden_queries.yaml uv run --locked python -m tools.eval.cli --full --ci --search adaptive --baseline tools/eval/baselines/core-adaptive.json --quality-only

# Evaluate the separate stress population against its own baseline.
stress:
    KB_PATH=tests/fixtures/eval_kb EVAL_GOLDEN_QUERIES=tests/fixtures/eval_golden_queries.yaml uv run --locked python -m tools.eval.cli --ci-stress --search adaptive --baseline tools/eval/baselines/stress-adaptive.json --quality-only

# Verify the installed wheel in an isolated environment outside the source tree.
package:
    uv run --locked python -m tools.verify_package

# Compare every standard battle KB and mode with its observed baseline.
battle:
    uv run --locked python -m tools.eval.battle_royale --output-dir tools/eval/results/runs/battle --label verification --detail-reports --baseline-dir tools/eval/baselines/battle-standard --quality-only

# Compare the challenge populations with their separate observed baselines.
battle-challenge:
    uv run --locked python -m tools.eval.battle_royale --suite tests/fixtures/eval_battle_royale_challenge.yaml --output-dir tools/eval/results/runs/battle --label verification-challenge --detail-reports --baseline-dir tools/eval/baselines/battle-challenge --quality-only

# Run model, package, and evaluation checks. Model preparation may require a download.
integration:
    uv run --locked python -m pytest -m "slow or transport" -q
    just package
    just eval
    just stress
    just battle
    just battle-challenge

# Run all locally reproducible checks, using the same recipes as CI.
slow: check
    just integration

# Drive the real CLI, MCP server, and wheel (verify-trace skill). Pass all, list, control, or drive names.
verify *args:
    .agents/skills/verify-trace/verify {{args}}
