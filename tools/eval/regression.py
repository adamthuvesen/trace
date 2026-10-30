"""Regression detection for evaluation results."""

from __future__ import annotations

import json
from pathlib import Path

from tools.eval.models import EvaluationReport, QueryRegression, RegressionReport
from tools.eval.provenance import comparison_differences

EVAL_DIR = Path(__file__).parent
BASELINES_DIR = EVAL_DIR / "results" / "baselines"

# A run regresses when it falls this far below its baseline.
TOP_1_DROP_TOLERANCE = 0.05
TOP_5_DROP_TOLERANCE = 0.03
LATENCY_INCREASE_TOLERANCE = 0.50
MIN_REGRESSED_QUERIES = 2


def load_baseline(baseline_path: Path) -> EvaluationReport:
    """Load a baseline report from JSON."""
    with baseline_path.open() as f:
        data = json.load(f)
    return EvaluationReport.from_dict(data)


def get_latest_baseline(search_mode: str | None = None) -> Path | None:
    """Get the most recent baseline file, optionally filtered by search mode."""
    baselines = list(BASELINES_DIR.glob("*.json"))
    if not baselines:
        return None

    if search_mode:
        baselines = [b for b in baselines if search_mode in b.stem]

    if not baselines:
        return None

    baselines.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return baselines[0]


def compare_results(
    current: EvaluationReport,
    baseline: EvaluationReport,
    *,
    compare_latency: bool = True,
) -> RegressionReport:
    """Compare current results against baseline and detect regressions."""
    current = EvaluationReport.from_dict(current.to_dict())
    baseline = EvaluationReport.from_dict(baseline.to_dict())
    experiment_differences = comparison_differences(
        current.manifest, baseline.manifest, compare_latency=compare_latency
    )

    top_1_delta = current.top_1_path_accuracy - baseline.top_1_path_accuracy
    top_5_delta = current.top_5_path_accuracy - baseline.top_5_path_accuracy

    if baseline.latency_p95_ms > 0:
        latency_delta_pct = (
            current.latency_p95_ms - baseline.latency_p95_ms
        ) / baseline.latency_p95_ms
    else:
        latency_delta_pct = 0.0

    current_results = {r.query_id: r for r in current.results}
    baseline_results = {r.query_id: r for r in baseline.results}

    regressed_queries = []
    improved_queries = []

    for query_id in sorted(current_results):
        curr = current_results[query_id]
        base = baseline_results[query_id]

        if base.top_1_path_hit and not curr.top_1_path_hit:
            regressed_queries.append(
                QueryRegression(
                    query_id=query_id,
                    query=curr.query,
                    baseline_passed=True,
                    current_passed=False,
                    baseline_path=base.retrieved_path,
                    current_path=curr.retrieved_path,
                )
            )

        elif not base.top_1_path_hit and curr.top_1_path_hit:
            improved_queries.append(
                QueryRegression(
                    query_id=query_id,
                    query=curr.query,
                    baseline_passed=False,
                    current_passed=True,
                    baseline_path=base.retrieved_path,
                    current_path=curr.retrieved_path,
                )
            )

    has_regression = (
        top_1_delta < -TOP_1_DROP_TOLERANCE
        or top_5_delta < -TOP_5_DROP_TOLERANCE
        or (compare_latency and latency_delta_pct > LATENCY_INCREASE_TOLERANCE)
        or len(regressed_queries) >= MIN_REGRESSED_QUERIES
    )

    return RegressionReport(
        baseline_timestamp=baseline.timestamp,
        current_timestamp=current.timestamp,
        baseline_top_1=baseline.top_1_path_accuracy,
        current_top_1=current.top_1_path_accuracy,
        baseline_top_5=baseline.top_5_path_accuracy,
        current_top_5=current.top_5_path_accuracy,
        baseline_latency_p95=baseline.latency_p95_ms,
        current_latency_p95=current.latency_p95_ms,
        top_1_delta=top_1_delta,
        top_5_delta=top_5_delta,
        latency_delta_pct=latency_delta_pct,
        has_regression=has_regression,
        regressed_queries=regressed_queries,
        improved_queries=improved_queries,
        experiment_differences=experiment_differences,
        latency_compared=compare_latency,
    )


def regression_failures(report: EvaluationReport) -> list[str]:
    """Return why a report fails its baseline comparison, or nothing when it passes."""
    report = EvaluationReport.from_dict(report.to_dict())
    if report.manifest is None:
        raise ValueError(
            "CI checks require evaluation provenance. Historical reports are readable only."
        )
    regression = report.regression
    if regression is None:
        raise ValueError("CI checks require a baseline comparison. Supply --baseline.")
    if not regression.has_regression:
        return []
    return [
        f"Regression against baseline: Top-1 {regression.top_1_delta:+.1%}, "
        f"Top-5 {regression.top_5_delta:+.1%}, "
        f"{len(regression.regressed_queries)} queries regressed"
    ]


def promote_to_baseline(report: EvaluationReport, output_path: Path | None = None) -> Path:
    """Promote an evaluation report to be the new baseline."""
    EvaluationReport.from_dict(report.to_dict())
    if report.manifest is None:
        raise ValueError("Cannot promote a report without evaluation provenance")
    failures = regression_failures(report) if report.regression else []
    if failures:
        raise ValueError("Cannot promote failed evaluation: " + "; ".join(failures))
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)

    if output_path is None:
        ts = report.timestamp.replace(":", "-").replace("+", "_")
        output_path = BASELINES_DIR / f"baseline_{report.search_mode}_{ts}.json"

    with output_path.open("w") as f:
        json.dump(report.to_dict(), f, indent=2)

    return output_path
