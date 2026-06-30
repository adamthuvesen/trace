"""Report generation for evaluation results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from tools.eval import load_thresholds

if TYPE_CHECKING:
    from tools.eval.models import EvaluationReport


def get_status_indicator(
    value: float, target: float, warning: float, critical: float
) -> str:
    """Get a status indicator based on thresholds (higher value is better)."""
    if value >= target:
        return "✓"
    elif value >= warning:
        return "~"
    elif value >= critical:
        return "!"
    else:
        return "✗"


def get_latency_status(
    latency_ms: float, target: float, warning: float, critical: float
) -> str:
    """Get a status indicator for latency (lower is better)."""
    if latency_ms <= target:
        return "✓"
    elif latency_ms <= warning:
        return "~"
    elif latency_ms <= critical:
        return "!"
    else:
        return "✗"


def generate_json_report(report: EvaluationReport) -> str:
    """Generate JSON report for programmatic comparison."""
    return json.dumps(report.to_dict(), indent=2)


def _append_markdown_header(lines: list[str], report: EvaluationReport) -> None:
    lines.extend(
        [
            "# Wiki Search Evaluation Report",
            "",
            f"**Timestamp:** {report.timestamp}",
            f"**Search Mode:** {report.search_mode}",
            f"**Embedding Model:** {report.embedding_model}",
            f"**Total Queries:** {report.total_queries}",
            f"**Quick Set Only:** {'Yes' if report.quick_set_only else 'No'}",
        ]
    )
    if report.adaptive_fallback_rate is not None:
        lines.append(f"**Adaptive fallback rate:** {report.adaptive_fallback_rate:.1%}")
    lines.append("")


def _append_markdown_run_flags(lines: list[str], report: EvaluationReport) -> None:
    run_flags = []
    if report.stress_only:
        run_flags.append("stress subset")
    elif report.include_stress:
        run_flags.append("includes stress queries")
    if report.strict_keywords:
        run_flags.append(
            "strict keywords"
            + (" (top-1 scope)" if report.strict_keywords_top1 else "")
        )
    if run_flags:
        lines.extend(["**Eval mode:** " + ", ".join(run_flags), ""])


def _append_markdown_overall_metrics(
    lines: list[str],
    report: EvaluationReport,
    path_thresh: dict,
    keyword_thresh: dict,
) -> None:
    t1_path_status = get_status_indicator(
        report.top_1_path_accuracy,
        path_thresh["top_1"]["target"],
        path_thresh["top_1"]["warning"],
        path_thresh["top_1"]["critical"],
    )
    t5_path_status = get_status_indicator(
        report.top_5_path_accuracy,
        path_thresh["top_5"]["target"],
        path_thresh["top_5"]["warning"],
        path_thresh["top_5"]["critical"],
    )
    t1_kw_status = get_status_indicator(
        report.top_1_keyword_accuracy,
        keyword_thresh["top_1"]["target"],
        keyword_thresh["top_1"]["warning"],
        keyword_thresh["top_1"]["critical"],
    )
    t5_kw_status = get_status_indicator(
        report.top_5_keyword_accuracy,
        keyword_thresh["top_5"]["target"],
        keyword_thresh["top_5"]["warning"],
        keyword_thresh["top_5"]["critical"],
    )

    lines.extend(
        [
            "## Overall Metrics",
            "",
            "| Metric | Value | Status | Target |",
            "|--------|-------|--------|--------|",
            f"| Top-1 Path Accuracy | {report.top_1_path_accuracy:.1%} | {t1_path_status} | ≥{path_thresh['top_1']['target']:.0%} |",
            f"| Top-5 Path Accuracy | {report.top_5_path_accuracy:.1%} | {t5_path_status} | ≥{path_thresh['top_5']['target']:.0%} |",
            f"| Top-1 Keyword Accuracy | {report.top_1_keyword_accuracy:.1%} | {t1_kw_status} | ≥{keyword_thresh['top_1']['target']:.0%} |",
            f"| Top-5 Keyword Accuracy | {report.top_5_keyword_accuracy:.1%} | {t5_kw_status} | ≥{keyword_thresh['top_5']['target']:.0%} |",
            f"| Mean Reciprocal Rank (path) | {report.mean_reciprocal_rank:.3f} | - | - |",
            f"| Within max_rank Path | {report.within_max_rank_path_accuracy:.1%} | - | - |",
            "",
        ]
    )


def _append_markdown_latency(
    lines: list[str],
    report: EvaluationReport,
    latency_thresh: dict,
) -> None:
    lines.extend(
        [
            "## Latency",
            "",
            "| Percentile | Value | Target |",
            "|------------|-------|--------|",
            f"| p50 | {report.latency_p50_ms:.1f}ms | ≤{latency_thresh['p50']['target']}ms |",
            f"| p95 | {report.latency_p95_ms:.1f}ms | ≤{latency_thresh['p95']['target']}ms |",
            f"| p99 | {report.latency_p99_ms:.1f}ms | ≤{latency_thresh['p99']['target']}ms |",
            f"| mean | {report.latency_mean_ms:.1f}ms | - |",
            "",
        ]
    )


def _append_markdown_category_metrics(
    lines: list[str],
    report: EvaluationReport,
) -> None:
    lines.extend(
        [
            "## By Category",
            "",
            "| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |",
            "|----------|---------|------------|------------|----------|---------|",
        ]
    )
    for cat_name in sorted(report.by_category.keys()):
        cat = report.by_category[cat_name]
        lines.append(
            f"| {cat.category} | {cat.query_count} | "
            f"{cat.top_1_path_accuracy:.0%} | {cat.top_5_path_accuracy:.0%} | "
            f"{cat.top_1_keyword_accuracy:.0%} | {cat.avg_latency_ms:.1f}ms |"
        )

    lines.append("")


def _append_markdown_file_type_metrics(
    lines: list[str],
    report: EvaluationReport,
) -> None:
    lines.extend(
        [
            "## By File Type",
            "",
            "| Type | Queries | Top-1 | Top-5 | Latency |",
            "|------|---------|-------|-------|---------|",
        ]
    )

    for ft_name in sorted(report.by_file_type.keys()):
        ft = report.by_file_type[ft_name]
        lines.append(
            f"| {ft.file_type} | {ft.query_count} | "
            f"{ft.top_1_accuracy:.0%} | {ft.top_5_accuracy:.0%} | "
            f"{ft.avg_latency_ms:.1f}ms |"
        )

    lines.append("")


def _append_markdown_regression(lines: list[str], report: EvaluationReport) -> None:
    if report.regression:
        reg = report.regression
        lines.extend(
            [
                "## Regression Analysis",
                "",
                f"**Baseline:** {reg.baseline_timestamp}",
                f"**Has Regression:** {'Yes' if reg.has_regression else 'No'}",
                "",
                "| Metric | Baseline | Current | Delta |",
                "|--------|----------|---------|-------|",
                f"| Top-1 Accuracy | {reg.baseline_top_1:.1%} | {reg.current_top_1:.1%} | {reg.top_1_delta:+.1%} |",
                f"| Top-5 Accuracy | {reg.baseline_top_5:.1%} | {reg.current_top_5:.1%} | {reg.top_5_delta:+.1%} |",
                f"| Latency p95 | {reg.baseline_latency_p95:.1f}ms | {reg.current_latency_p95:.1f}ms | {reg.latency_delta_pct:+.0%} |",
                "",
            ]
        )

        if reg.regressed_queries:
            lines.extend(
                [
                    "### Regressed Queries (pass → fail)",
                    "",
                ]
            )
            for q in reg.regressed_queries:
                lines.append(f"- **{q.query_id}**: {q.query}")
                lines.append(f"  - Baseline: `{q.baseline_path}`")
                lines.append(f"  - Current: `{q.current_path}`")
            lines.append("")

        if reg.improved_queries:
            lines.extend(
                [
                    "### Improved Queries (fail → pass)",
                    "",
                ]
            )
            for q in reg.improved_queries:
                lines.append(f"- **{q.query_id}**: {q.query}")
            lines.append("")


def _append_markdown_failures(lines: list[str], report: EvaluationReport) -> None:
    failed = [r for r in report.results if not r.top_1_path_hit]
    if failed:
        lines.extend(
            [
                "## Failed Queries (Top-1 Miss)",
                "",
                "| Query ID | Query | Retrieved Path |",
                "|----------|-------|----------------|",
            ]
        )
        for r in failed[:20]:
            query_short = r.query[:40] + "..." if len(r.query) > 40 else r.query
            path_short = (
                r.retrieved_path[:50] + "..."
                if len(r.retrieved_path) > 50
                else r.retrieved_path
            )
            lines.append(f"| {r.query_id} | {query_short} | {path_short} |")

        if len(failed) > 20:
            lines.append(f"| ... | {len(failed) - 20} more | ... |")

        lines.append("")


def generate_markdown_report(report: EvaluationReport) -> str:
    """Generate markdown report for human review."""
    thresholds = load_thresholds()
    lines: list[str] = []

    _append_markdown_header(lines, report)
    _append_markdown_run_flags(lines, report)
    _append_markdown_overall_metrics(
        lines,
        report,
        thresholds["path_accuracy"],
        thresholds["keyword_accuracy"],
    )
    _append_markdown_latency(lines, report, thresholds["latency"])
    _append_markdown_category_metrics(lines, report)
    _append_markdown_file_type_metrics(lines, report)
    _append_markdown_regression(lines, report)
    _append_markdown_failures(lines, report)
    return "\n".join(lines)


def _append_console_header(lines: list[str], report: EvaluationReport) -> None:
    lines.extend(
        [
            "",
            "=" * 60,
            "WIKI SEARCH EVALUATION REPORT",
            "=" * 60,
            "",
            f"Timestamp:       {report.timestamp}",
            f"Search Mode:     {report.search_mode}",
            f"Embedding Model: {report.embedding_model}",
            f"Total Queries:   {report.total_queries}",
            f"Quick Set Only:  {'Yes' if report.quick_set_only else 'No'}",
        ]
    )
    if report.stress_only:
        lines.append("Eval subset:     stress only")
    elif report.include_stress:
        lines.append("Eval subset:     core + stress")
    if report.strict_keywords:
        scope = " (top-1 body only)" if report.strict_keywords_top1 else ""
        lines.append(f"Keyword mode:    strict{scope}")
    lines.append("")


def _console_status_str(
    value: float,
    target: float,
    warning: float,
    critical: float,
) -> str:
    indicator = get_status_indicator(value, target, warning, critical)
    if indicator == "✓":
        return f"{value:.1%} [PASS]"
    if indicator == "~":
        return f"{value:.1%} [WARN]"
    if indicator == "!":
        return f"{value:.1%} [ATTN]"
    return f"{value:.1%} [FAIL]"


def _append_console_accuracy(
    lines: list[str],
    report: EvaluationReport,
    path_thresh: dict,
    keyword_thresh: dict,
) -> None:
    lines.extend(
        [
            "-" * 40,
            "ACCURACY METRICS",
            "-" * 40,
            f"Top-1 Path:    {_console_status_str(report.top_1_path_accuracy, path_thresh['top_1']['target'], path_thresh['top_1']['warning'], path_thresh['top_1']['critical'])} (target: ≥{path_thresh['top_1']['target']:.0%})",
            f"Top-5 Path:    {_console_status_str(report.top_5_path_accuracy, path_thresh['top_5']['target'], path_thresh['top_5']['warning'], path_thresh['top_5']['critical'])} (target: ≥{path_thresh['top_5']['target']:.0%})",
            f"Top-1 Keyword: {_console_status_str(report.top_1_keyword_accuracy, keyword_thresh['top_1']['target'], keyword_thresh['top_1']['warning'], keyword_thresh['top_1']['critical'])} (target: ≥{keyword_thresh['top_1']['target']:.0%})",
            f"Top-5 Keyword: {_console_status_str(report.top_5_keyword_accuracy, keyword_thresh['top_5']['target'], keyword_thresh['top_5']['warning'], keyword_thresh['top_5']['critical'])} (target: ≥{keyword_thresh['top_5']['target']:.0%})",
            f"MRR (path):      {report.mean_reciprocal_rank:.3f}",
            f"Within max_rank: {report.within_max_rank_path_accuracy:.1%}",
            "",
        ]
    )


def _append_console_latency(lines: list[str], report: EvaluationReport) -> None:
    lines.extend(
        [
            "-" * 40,
            "LATENCY",
            "-" * 40,
            f"p50:  {report.latency_p50_ms:6.1f}ms",
            f"p95:  {report.latency_p95_ms:6.1f}ms",
            f"p99:  {report.latency_p99_ms:6.1f}ms",
            f"mean: {report.latency_mean_ms:6.1f}ms",
            "",
        ]
    )


def _append_console_category_metrics(
    lines: list[str],
    report: EvaluationReport,
) -> None:
    lines.extend(
        [
            "-" * 40,
            "BY CATEGORY",
            "-" * 40,
            f"{'Category':<12} {'Queries':>7} {'Top-1':>6} {'Top-5':>6}",
        ]
    )

    for cat_name in sorted(report.by_category.keys()):
        cat = report.by_category[cat_name]
        lines.append(
            f"{cat.category:<12} {cat.query_count:>7} "
            f"{cat.top_1_path_accuracy:>5.0%} {cat.top_5_path_accuracy:>5.0%}"
        )

    lines.append("")


def _append_console_file_type_metrics(
    lines: list[str],
    report: EvaluationReport,
) -> None:
    lines.extend(
        [
            "-" * 40,
            "BY FILE TYPE",
            "-" * 40,
            f"{'Type':<8} {'Queries':>7} {'Top-1':>6} {'Top-5':>6}",
        ]
    )

    for ft_name in sorted(report.by_file_type.keys()):
        ft = report.by_file_type[ft_name]
        lines.append(
            f"{ft.file_type:<8} {ft.query_count:>7} "
            f"{ft.top_1_accuracy:>5.0%} {ft.top_5_accuracy:>5.0%}"
        )

    lines.append("")


def _append_console_regression(lines: list[str], report: EvaluationReport) -> None:
    if report.regression:
        reg = report.regression
        lines.extend(
            [
                "-" * 40,
                "REGRESSION ANALYSIS",
                "-" * 40,
                f"Baseline: {reg.baseline_timestamp}",
                f"Status:   {'REGRESSION DETECTED' if reg.has_regression else 'OK'}",
                f"Top-1 Delta: {reg.top_1_delta:+.1%}",
                f"Top-5 Delta: {reg.top_5_delta:+.1%}",
                f"Latency Delta: {reg.latency_delta_pct:+.0%}",
            ]
        )

        if reg.regressed_queries:
            lines.append(f"Regressed Queries: {len(reg.regressed_queries)}")
            for q in reg.regressed_queries[:5]:
                lines.append(f"  - {q.query_id}: {q.query[:40]}")

        if reg.improved_queries:
            lines.append(f"Improved Queries: {len(reg.improved_queries)}")

        lines.append("")


def generate_console_report(report: EvaluationReport) -> str:
    """Generate colored console report."""
    thresholds = load_thresholds()
    lines: list[str] = []

    _append_console_header(lines, report)
    _append_console_accuracy(
        lines,
        report,
        thresholds["path_accuracy"],
        thresholds["keyword_accuracy"],
    )
    _append_console_latency(lines, report)
    _append_console_category_metrics(lines, report)
    _append_console_file_type_metrics(lines, report)
    _append_console_regression(lines, report)
    lines.extend(
        [
            "=" * 60,
            "",
        ]
    )

    return "\n".join(lines)


def save_report(
    report: EvaluationReport,
    output_dir: Path,
    formats: list[str] | None = None,
) -> dict[str, Path]:
    """Save report in multiple formats."""
    if formats is None:
        formats = ["json", "md"]

    output_dir.mkdir(parents=True, exist_ok=True)

    ts = report.timestamp.replace(":", "-").replace("+", "_")
    base_name = f"eval_{report.search_mode}_{ts}"

    saved = {}

    if "json" in formats:
        json_path = output_dir / f"{base_name}.json"
        json_path.write_text(generate_json_report(report))
        saved["json"] = json_path

    if "md" in formats:
        md_path = output_dir / f"{base_name}.md"
        md_path.write_text(generate_markdown_report(report))
        saved["md"] = md_path

    return saved
