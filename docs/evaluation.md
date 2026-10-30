# Evaluation

Use the committed fixture gates to check retrieval quality against observed baselines.
The full gate runs every core query.
The stress gate runs a separate population.

```bash
just eval
just stress
```

These commands run 17 core queries and 12 stress queries respectively.
They use temporary indexes even when `INDEX_PATH` names a served index.
The battle CLI also uses temporary indexes.
Model preparation can require downloads, as described in [development.md](development.md#models-and-network-prerequisites).

## Commands and scope

Run the evaluation CLI:

```bash
KB_PATH=tests/fixtures/eval_kb EVAL_GOLDEN_QUERIES=tests/fixtures/eval_golden_queries.yaml \
  uv run --locked python -m tools.eval.cli --full --search adaptive
```

The default scope is quick queries.
`--full` includes every core query.
Stress queries are excluded unless `--include-stress` or `--stress` selects them.
`--ci-stress` selects stress queries without the quick filter.
`--category` and `--file-type` further restrict the population.
An empty selected scope fails before index construction.

For a private knowledge base:

```bash
cp tools/eval/golden_queries.example.yaml tools/eval/golden_queries.yaml
KB_PATH=/path/to/docs uv run --locked python -m tools.eval.cli --full --search adaptive
```

The local query file is gitignored.
`EVAL_GOLDEN_QUERIES` selects another YAML file.
Invalid settings never silently select a fallback file.
Query files reject unknown fields, duplicate IDs, malformed booleans, and invalid ranks.
Numeric YAML keywords remain supported because the public HTTP fixtures use them.
The whole query file is validated before subset filtering.

## Metric contract

The current metric version preserves the shipped path, keyword, and percentile definitions.

| Metric | Definition |
| --- | --- |
| Top-1 path | Expected or alternate path matches the first result |
| Top-5 path | Expected or alternate path appears in the first five returned results |
| MRR | Reciprocal of the first matching path rank within `top_k`, or zero |
| Within max_rank | First matching rank satisfies the query limit, defaulting to `top_k` |
| Top-1 keyword | Case-insensitive substring matches in the first result meet the keyword requirement |
| Top-5 keyword | Matches across the returned `top_k` result bodies meet the requirement |
| Latency percentiles | Inclusive linear interpolation over observed query latencies |

The historical Top-5 keyword name refers to the configured retrieval scope.
It can cover more than five results when `top_k` exceeds five.
The Top-5 path metric still checks five results.
Keyword matching requires two keywords by default (`DEFAULT_MIN_KEYWORDS` in `tools/eval/models.py`).
A query's `min_keywords` overrides that requirement.
`--strict-keywords` requires every expected keyword unless the query overrides it.
`--strict-keywords-top1` restricts both keyword metrics to the first result body.

The evaluator warms the embedding backend before timing.
It clears the query embedding cache, then times each search call.
Timing excludes index construction, report generation, and application rendering.
The manifest names this protocol explicitly.
It does not represent end-to-end CLI or MCP latency.

## Manifests and comparisons

Current reports derive metrics and category/file-type breakdowns from their result rows.
Loading, comparison, CI checks, and promotion reject contradictory aggregates or manifest settings.
Historical reports retain an explicit legacy decoding path.

Every new report records:

- Corpus fingerprint from relative source paths and content hashes.
- Selected query IDs, query-set fingerprint, and selection scope.
- Metric version, mode, `top_k`, and keyword settings.
- Actual build recipe, source revision, and source fingerprint.
- Latency protocol and host/interpreter description.

Fingerprints exclude absolute KB paths and source mtimes.
The manifest stores query IDs without query text.
Detailed result rows still include query text, so keep private reports local.

A comparison requires identical input populations and measurement semantics.
Changed corpus, query set, selection, metric version, `top_k`, or keyword rules cause an explicit error.
Different modes, model recipes, or source revisions are recorded as experiment differences.
They can be compared on the same inputs.
The committed baseline is the only quality gate.
A run regresses when Top-1 drops more than 5 points, Top-5 drops more than 3 points, or two queries lose their Top-1 hit.
The tolerances live in `tools/eval/regression.py`.

```bash
KB_PATH=tests/fixtures/eval_kb EVAL_GOLDEN_QUERIES=tests/fixtures/eval_golden_queries.yaml \
  uv run --locked python -m tools.eval.cli --full --ci --search adaptive \
  --baseline tools/eval/baselines/core-adaptive.json --quality-only
```

`--quality-only` excludes baseline latency regression from the comparison gate.
Latency values and deltas remain visible but do not gate.
Use it for quality comparisons across hosts.
A latency comparison rejects different recorded host/interpreter descriptions.
Matching descriptions alone do not establish equal hardware, load, or timing noise.

CI requires a comparative baseline.
A missing requested baseline fails instead of skipping comparison.
`just eval` and `just stress` select explicit committed baselines.
Reports appear under the ignored `tools/eval/results/runs/` directory by default.

## Historical reports and baseline promotion

The loader reads shipped count-based and accuracy-only reports.
It also reads the retired `reranked` mode without changing its meaning.
Reports without manifests remain historical artifacts.
Regression comparison rejects their missing provenance.

The committed fixture baselines contain observed runs from 2026-11-04 at revision `2ef64eb`.
Their explicit migration notes explain reconstructed provenance from the matching source inventory, source code, and build parameters.
The migration preserves their recorded quality and latency values.
It does not infer provenance automatically for other historical reports.

`--promote` validates the report and refuses it when it regresses against the supplied baseline.
A failed evaluation cannot replace a baseline.
When changing the committed fixture baseline, review its source observations and manifest together.

## Battle suites

```bash
uv run --locked python -m tools.eval.battle_royale \
  --output-dir tools/eval/results/runs/battle --label local --detail-reports
uv run --locked python -m tools.eval.battle_royale \
  --suite tests/fixtures/eval_battle_royale_challenge.yaml \
  --output-dir tools/eval/results/runs/battle --label local-challenge --detail-reports
```

Suite loading validates modes, unique KB IDs, paths, and every selected query population before loading a model.
Summaries contain each KB/mode manifest.
`--detail-reports` also writes individual reports.
Add `--baseline-dir tools/eval/baselines/battle-standard --quality-only` to gate the standard suite.
Use `tools/eval/baselines/battle-challenge` for the challenge suite.
`just integration` runs both comparative gates.
Use `just battle` or `just battle-challenge` to run either gate separately.
Each gate uses the same baseline tolerances for every selected KB and search mode.
Missing, malformed, or incompatible baselines fail before model initialization.
A regression returns a nonzero status and retains reports with the failing KB, mode, and query transitions.
Without `--baseline-dir`, the command remains an exploratory report run.

The 24 committed battle reports preserve observed runs and their recorded `b081c5f` source revision.
Their ranking outputs matched the original source in the refactor verification.
To update them, generate detail reports in a scratch output directory and inspect each proposed JSON replacement.
Review manifest changes, improvements, and regressions before committing baseline replacements.
Do not overwrite baselines automatically during verification.

## Focused tests

```bash
just test-file tests/test_eval_contracts.py
just test-file tests/test_eval_retrieval.py
```

The retrieval test uses a real embedding backend and a scratch index.
It includes the `slow` marker.
Historical benchmark artifacts remain under [benchmarks/](benchmarks/README.md).
