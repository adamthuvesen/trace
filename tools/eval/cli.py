#!/usr/bin/env python3
"""CLI for wiki search evaluation suite.

Usage:
    # Quick evaluation (~14 template queries)
    uv run python -m tools.eval.cli --quick

    # Full evaluation (~26 template queries)
    uv run python -m tools.eval.cli --full

    # Specific search mode
    uv run python -m tools.eval.cli --search semantic

    # Category filter
    uv run python -m tools.eval.cli --category concepts --category indexing

    # File type filter
    uv run python -m tools.eval.cli --file-type .pdf

    # Compare to baseline
    uv run python -m tools.eval.cli --baseline results/baselines/latest.json

    # CI mode (exit 1 on regression)
    uv run python -m tools.eval.cli --ci

    # Promote current results to baseline
    uv run python -m tools.eval.cli --promote
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from tools.eval.evaluator import load_golden_queries, run_evaluation
from tools.eval.regression import (
    check_ci_thresholds,
    compare_results,
    get_latest_baseline,
    load_baseline,
    promote_to_baseline,
)
from tools.eval.reporter import (
    generate_console_report,
    save_report,
)

EVAL_DIR = Path(__file__).parent
RESULTS_DIR = EVAL_DIR / "results"
RUNS_DIR = RESULTS_DIR / "runs"

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
logger = logging.getLogger(__name__)


@click.command()
@click.option(
    "--quick",
    is_flag=True,
    help="Run quick evaluation (~14 template queries)",
)
@click.option(
    "--full",
    is_flag=True,
    help="Run full evaluation (~26 template queries)",
)
@click.option(
    "--search",
    type=click.Choice(["semantic", "bm25", "hybrid"]),
    default="hybrid",
    help="Search mode to evaluate (default: hybrid)",
)
@click.option(
    "--category",
    multiple=True,
    help="Filter by category (can be repeated)",
)
@click.option(
    "--file-type",
    multiple=True,
    help="Filter by file type (e.g., .md, .pdf)",
)
@click.option(
    "--baseline",
    type=click.Path(exists=True, path_type=Path),
    help="Path to baseline JSON for regression comparison",
)
@click.option(
    "--ci",
    is_flag=True,
    help="CI mode: exit 1 on regression or critical threshold failure",
)
@click.option(
    "--promote",
    is_flag=True,
    help="Promote results to new baseline after evaluation",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Verbose output with per-query details",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=RUNS_DIR,
    help=f"Output directory for results (default: {RUNS_DIR})",
)
@click.option(
    "--ab",
    is_flag=True,
    help="Run torch vs onnx backends side-by-side and print a comparison",
)
def main(
    quick: bool,
    full: bool,
    search: str,
    category: tuple[str, ...],
    file_type: tuple[str, ...],
    baseline: Path | None,
    ci: bool,
    promote: bool,
    verbose: bool,
    output_dir: Path,
    ab: bool,
) -> None:
    """Run wiki search evaluation suite."""
    # Set log level
    if verbose:
        logging.getLogger("tools.eval").setLevel(logging.DEBUG)

    # Validate mutually exclusive flags
    if quick and full:
        raise click.UsageError("Cannot specify both --quick and --full")

    # Default to quick if neither specified
    quick_only = quick or not full

    # Convert category and file_type tuples to lists
    categories = list(category) if category else None
    file_types = list(file_type) if file_type else None

    # Show query count
    queries = load_golden_queries(
        quick_only=quick_only,
        categories=categories,
        file_types=file_types,
    )
    click.echo(f"Loaded {len(queries)} queries for evaluation")

    # Initialize indexer
    from trace_search.config import settings
    from trace_search.indexer import WikiIndexer

    click.echo(f"Knowledge base: {settings.kb_path}")
    click.echo(f"Search mode: {search}")
    click.echo(f"Embedding model: {settings.embedding_model}")
    click.echo()

    if ab:
        _run_ab(
            search_mode=search,
            quick_only=quick_only,
            categories=categories,
            file_types=file_types,
        )
        return

    indexer = WikiIndexer()

    # Ensure index exists
    if indexer.collection.count() == 0:
        click.echo("Building index (first time)...")
        indexer.build_index()
    else:
        click.echo(f"Using existing index: {indexer.collection.count()} chunks")

    # Mirror production bootstrap: warm the embedding model so eval p95 reflects
    # what real MCP consumers see. Set EMBEDDING_WARMUP_ENABLED=false to
    # measure cold-path latency explicitly.
    from trace_search.server_app import warm_embedding_model

    warm_embedding_model(indexer.backend)

    click.echo()

    # Run evaluation
    click.echo("Running evaluation...")
    report = run_evaluation(
        indexer=indexer,
        search_mode=search,
        quick_only=quick_only,
        categories=categories,
        file_types=file_types,
    )

    # Compare to baseline if specified
    if baseline:
        click.echo(f"Loading baseline: {baseline}")
        baseline_report = load_baseline(baseline)
        report.regression = compare_results(report, baseline_report)
    elif ci:
        # In CI mode, try to find latest baseline automatically
        latest = get_latest_baseline(search_mode=search)
        if latest:
            click.echo(f"Using latest baseline: {latest}")
            baseline_report = load_baseline(latest)
            report.regression = compare_results(report, baseline_report)
        else:
            click.echo("No baseline found, skipping regression check")

    # Print console report
    click.echo(generate_console_report(report))

    # Save reports
    saved = save_report(report, output_dir, formats=["json", "md"])
    click.echo("Results saved to:")
    for fmt, path in saved.items():
        click.echo(f"  {fmt}: {path}")

    # Promote to baseline if requested
    if promote:
        baseline_path = promote_to_baseline(report)
        click.echo(f"Promoted to baseline: {baseline_path}")

    # CI mode: check thresholds and exit code
    if ci:
        passed, failures = check_ci_thresholds(report)
        if not passed:
            click.echo()
            click.echo("CI FAILURES:")
            for failure in failures:
                click.echo(f"  - {failure}")
            sys.exit(1)
        else:
            click.echo()
            click.echo("CI: All thresholds passed")


def _run_ab(
    search_mode: str,
    quick_only: bool,
    categories: list[str] | None,
    file_types: list[str] | None,
) -> None:
    """Run the golden set under torch then onnx and print a side-by-side report."""
    import os

    from trace_search.config import get_settings
    from trace_search.embeddings import build_embedding_backend
    from trace_search.indexer import WikiIndexer
    from trace_search.search import SemanticSearch
    from trace_search.server_app import warm_embedding_model

    results: dict[str, dict] = {}
    per_query_top1: dict[str, dict[str, str]] = {}

    for backend_name in ("torch", "onnx"):
        os.environ["EMBEDDING_BACKEND"] = backend_name
        get_settings.cache_clear()
        SemanticSearch._embedding_cache.clear()
        SemanticSearch._cache_hits = 0
        SemanticSearch._cache_misses = 0

        click.echo(f"\n=== Running backend: {backend_name} ===")
        backend = build_embedding_backend()
        indexer = WikiIndexer(backend=backend)
        if indexer.collection.count() == 0:
            indexer.build_index()
        warm_embedding_model(indexer.backend)

        report = run_evaluation(
            indexer=indexer,
            search_mode=search_mode,
            quick_only=quick_only,
            categories=categories,
            file_types=file_types,
        )
        results[backend_name] = {
            "top1_path": report.top_1_path_accuracy,
            "top5_path": report.top_5_path_accuracy,
            "top1_keyword": report.top_1_keyword_accuracy,
            "top5_keyword": report.top_5_keyword_accuracy,
            "p50": report.latency_p50_ms,
            "p95": report.latency_p95_ms,
        }
        per_query_top1[backend_name] = {
            qr.query_id: qr.retrieved_path for qr in report.results
        }

    click.echo("\n=== A/B SUMMARY ===")
    click.echo(f"{'metric':<18}{'torch':>14}{'onnx':>14}{'delta':>14}")
    for metric in ("top1_path", "top5_path", "top1_keyword", "top5_keyword"):
        t = results["torch"][metric]
        o = results["onnx"][metric]
        click.echo(f"{metric:<18}{t:>13.1%} {o:>13.1%} {o - t:>+13.1%}")
    for metric in ("p50", "p95"):
        t = results["torch"][metric]
        o = results["onnx"][metric]
        click.echo(f"{metric + ' ms':<18}{t:>13.1f} {o:>13.1f} {o - t:>+13.1f}")

    diverged = [
        (qid, per_query_top1["torch"][qid], per_query_top1["onnx"][qid])
        for qid in per_query_top1["torch"]
        if per_query_top1["torch"][qid] != per_query_top1["onnx"][qid]
    ]
    click.echo(f"\nDiverged top-1 queries: {len(diverged)}")
    for qid, torch_path, onnx_path in diverged:
        click.echo(f"  - {qid}: torch={torch_path!r} vs onnx={onnx_path!r}")


if __name__ == "__main__":
    main()
