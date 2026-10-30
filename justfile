set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

# Install the locked development environment and document converters.
bootstrap:
    uv sync --locked --dev --extra convert

# Run the same fast checks locally and in CI.
check:
    uv run --locked --extra convert ruff check .
    uv run --locked --extra convert ruff format --check .
    uv run --locked --extra convert basedpyright
    just ratchet
    uv run --locked --extra convert lint-imports --no-logo
    uv run --locked --extra convert python -m pytest -m "not slow and not transport" -q -n auto

# Apply every auto-fixer.
fix:
    uv run --locked --extra convert ruff check --fix .
    uv run --locked --extra convert ruff format .

# Fail when the basedpyright baseline holds more errors than origin/main. The first baseline is allowed.
ratchet:
    #!/usr/bin/env bash
    set -euo pipefail
    count() { python3 -c 'import json,sys; print(sum(len(v) for v in json.load(sys.stdin)["files"].values()))'; }
    now=$(count < .basedpyright/baseline.json)
    if ! base=$(git show origin/main:.basedpyright/baseline.json 2>/dev/null | count 2>/dev/null); then
        echo "ratchet: no baseline on origin/main, allowing $now"; exit 0
    fi
    if [ "$now" -gt "$base" ]; then echo "ratchet: baseline grew from $base to $now" >&2; exit 1; fi
    echo "ratchet: baseline $now (origin/main $base)"

# Run one test file or pytest node.
test-file path:
    uv run --locked --extra convert python -m pytest {{quote(path)}} -q

# Evaluate every core fixture query against the committed baseline.
eval:
    KB_PATH=tests/fixtures/eval_kb EVAL_GOLDEN_QUERIES=tests/fixtures/eval_golden_queries.yaml uv run --locked --extra convert python -m tools.eval.cli --full --ci --search adaptive --baseline tools/eval/baselines/core-adaptive.json --quality-only

# Evaluate the separate stress population against its own baseline.
stress:
    KB_PATH=tests/fixtures/eval_kb EVAL_GOLDEN_QUERIES=tests/fixtures/eval_golden_queries.yaml uv run --locked --extra convert python -m tools.eval.cli --ci-stress --search adaptive --baseline tools/eval/baselines/stress-adaptive.json --quality-only

# Verify the installed wheel in an isolated environment outside the source tree.
package:
    uv run --locked --extra convert python -m tools.verify_package

# Compare every standard battle KB and mode with its observed baseline.
battle:
    uv run --locked --extra convert python -m tools.eval.battle_royale --output-dir tools/eval/results/runs/battle --label verification --detail-reports --baseline-dir tools/eval/baselines/battle-standard --quality-only

# Compare the challenge populations with their separate observed baselines.
battle-challenge:
    uv run --locked --extra convert python -m tools.eval.battle_royale --suite tests/fixtures/eval_battle_royale_challenge.yaml --output-dir tools/eval/results/runs/battle --label verification-challenge --detail-reports --baseline-dir tools/eval/baselines/battle-challenge --quality-only

# Run model, package, and evaluation checks. Model preparation may require a download.
integration:
    uv run --locked --extra convert python -m pytest -m "slow or transport" -q
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
