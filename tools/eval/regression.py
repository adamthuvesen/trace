"""Regression detection for evaluation results."""

from __future__ import annotations

import json
from pathlib import Path

from tools.eval import load_thresholds
from tools.eval.models import EvaluationReport, QueryRegression, RegressionReport

EVAL_DIR = Path(__file__).parent
BASELINES_DIR = EVAL_DIR / "results" / "baselines"


def load_baseline(baseline_path: Path) -> EvaluationReport:
    """Load a baseline report from JSON."""
    with open(baseline_path) as f:
        data = json.load(f)
    return EvaluationReport.from_dict(data)


def get_latest_baseline(search_mode: str | None = None) -> Path | None:
    """Get the most recent baseline file, optionally filtered by search mode."""
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)

    baselines = list(BASELINES_DIR.glob("*.json"))
    if not baselines:
        return None

    # Filter by search mode if specified
    if search_mode:
        baselines = [b for b in baselines if search_mode in b.stem]

    if not baselines:
        return None

    # Sort by modification time, newest first
    baselines.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return baselines[0]


def compare_results(
    current: EvaluationReport,
    baseline: EvaluationReport,
) -> RegressionReport:
    """Compare current results against baseline and detect regressions."""
    thresholds = load_thresholds()
    reg_thresh = thresholds["regression"]

    # Calculate deltas
    top_1_delta = current.top_1_path_accuracy - baseline.top_1_path_accuracy
    top_5_delta = current.top_5_path_accuracy - baseline.top_5_path_accuracy

    # Calculate latency delta (percentage increase)
    if baseline.latency_p95_ms > 0:
        latency_delta_pct = (
            current.latency_p95_ms - baseline.latency_p95_ms
        ) / baseline.latency_p95_ms
    else:
        latency_delta_pct = 0.0

    # Build result maps for comparison
    current_results = {r.query_id: r for r in current.results}
    baseline_results = {r.query_id: r for r in baseline.results}

    # Find regressed and improved queries
    regressed_queries = []
    improved_queries = []

    for query_id in set(current_results.keys()) & set(baseline_results.keys()):
        curr = current_results[query_id]
        base = baseline_results[query_id]

        # Check for regression (pass -> fail)
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

        # Check for improvement (fail -> pass)
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

    # Determine if regression is significant
    has_regression = (
        # Accuracy dropped significantly
        top_1_delta < -reg_thresh["top_1_drop_threshold"]
        or top_5_delta < -reg_thresh["top_5_drop_threshold"]
        # Latency increased significantly
        or latency_delta_pct > reg_thresh["latency_increase_threshold"]
        # Enough individual queries regressed
        or len(regressed_queries) >= reg_thresh["min_regressed_queries"]
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
    )


def check_ci_thresholds(
    report: EvaluationReport,
    stress_subset: bool = False,
) -> tuple[bool, list[str]]:
    """Check if the report meets CI thresholds.

    When ``stress_subset`` is True, uses the optional ``stress`` block from
    thresholds.yaml (falling back to the default thresholds for missing keys).

    Returns:
        Tuple of (passed, list of failure reasons)
    """
    thresholds = load_thresholds()
    stress_cfg = thresholds.get("stress") if stress_subset else None
    if isinstance(stress_cfg, dict):
        path_thresh = stress_cfg.get("path_accuracy", thresholds["path_accuracy"])
        keyword_thresh = stress_cfg.get(
            "keyword_accuracy", thresholds["keyword_accuracy"]
        )
        latency_thresh = stress_cfg.get("latency", thresholds["latency"])
        ci_config = stress_cfg.get("ci", thresholds["ci"])
    else:
        path_thresh = thresholds["path_accuracy"]
        keyword_thresh = thresholds["keyword_accuracy"]
        latency_thresh = thresholds["latency"]
        ci_config = thresholds["ci"]

    failures = []

    prefix = "[stress] " if stress_subset else ""
    fail_on = ci_config.get("fail_on", [])

    # Check Top-1 accuracy
    if "top_1_below_critical" in fail_on:
        if report.top_1_path_accuracy < path_thresh["top_1"]["critical"]:
            failures.append(
                f"{prefix}Top-1 path accuracy ({report.top_1_path_accuracy:.1%}) below critical threshold ({path_thresh['top_1']['critical']:.0%})"
            )

    # Check Top-5 accuracy
    if "top_5_below_critical" in fail_on:
        if report.top_5_path_accuracy < path_thresh["top_5"]["critical"]:
            failures.append(
                f"{prefix}Top-5 path accuracy ({report.top_5_path_accuracy:.1%}) below critical threshold ({path_thresh['top_5']['critical']:.0%})"
            )

    # Check keyword accuracy (optional in CI config)
    if "top_1_keyword_below_critical" in fail_on:
        crit = keyword_thresh["top_1"]["critical"]
        if report.top_1_keyword_accuracy < crit:
            failures.append(
                f"{prefix}Top-1 keyword accuracy ({report.top_1_keyword_accuracy:.1%}) below critical threshold ({crit:.0%})"
            )
    if "top_5_keyword_below_critical" in fail_on:
        crit = keyword_thresh["top_5"]["critical"]
        if report.top_5_keyword_accuracy < crit:
            failures.append(
                f"{prefix}Top-5 keyword accuracy ({report.top_5_keyword_accuracy:.1%}) below critical threshold ({crit:.0%})"
            )

    if "mrr_below_critical" in fail_on:
        crit = ci_config.get("mrr_critical", 0.0)
        if report.mean_reciprocal_rank < crit:
            failures.append(
                f"{prefix}Mean reciprocal rank ({report.mean_reciprocal_rank:.3f}) below critical threshold ({crit:.3f})"
            )

    # Check latency
    if "latency_above_critical" in fail_on:
        if report.latency_p95_ms > latency_thresh["p95"]["critical"]:
            failures.append(
                f"{prefix}Latency p95 ({report.latency_p95_ms:.1f}ms) above critical threshold ({latency_thresh['p95']['critical']}ms)"
            )

    # Check regression
    if "regression_detected" in fail_on:
        if report.regression and report.regression.has_regression:
            failures.append(
                f"{prefix}Regression detected: Top-1 delta {report.regression.top_1_delta:+.1%}, "
                f"{len(report.regression.regressed_queries)} queries regressed"
            )

    return len(failures) == 0, failures


def promote_to_baseline(
    report: EvaluationReport, output_path: Path | None = None
) -> Path:
    """Promote an evaluation report to be the new baseline."""
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)

    if output_path is None:
        ts = report.timestamp.replace(":", "-").replace("+", "_")
        output_path = BASELINES_DIR / f"baseline_{report.search_mode}_{ts}.json"

    with open(output_path, "w") as f:
        json.dump(report.to_dict(), f, indent=2)

    return output_path
