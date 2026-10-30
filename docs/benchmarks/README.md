# Benchmark artifacts

These files preserve historical run data.
Their timestamps, query populations, code, and timing protocols can differ.
A filename such as `current` does not establish freshness.
The retrieval guide labels the dated [challenge results](../retrieval-modes.md#historical-challenge-results).

The June 13 `eval_*.json` reports support the historical table in [README.md](../../README.md#historical-benchmark-results).
The [September 29 note](2026-09-29-trace-overhaul.md) describes later experiments.
Existing historical JSON remains readable, including the retired `reranked` mode.
Reports without manifests cannot enter the current regression comparator.

Current fixture gates use [core-adaptive.json](../../tools/eval/baselines/core-adaptive.json) and [stress-adaptive.json](../../tools/eval/baselines/stress-adaptive.json).
Those baselines preserve observed November 4 runs and contain explicit historical provenance migration notes.
The [evaluation guide](../evaluation.md) defines the input, metric, and promotion contracts.
The [November 4 verification report](2026-11-04-agentic-refactor.md) records refactor coverage, historical replays, and environmental limits.

```bash
just eval
just stress
```

Use fresh manifest-bearing reports for new experiments.
Keep private query text and paths outside committed artifacts.
Cross-host quality comparisons use `--quality-only`.
A performance claim also requires a suitable timing experiment and evidence about load and measurement noise.
