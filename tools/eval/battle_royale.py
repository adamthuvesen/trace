#!/usr/bin/env python3
"""Run retrieval evaluations across multiple committed fixture knowledge bases."""

from __future__ import annotations

import statistics
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, NotRequired, Self, TypedDict

from pydantic import Field, TypeAdapter, model_validator

from tools.eval.models import (
    EvalModel,
    EvaluationManifest,
    EvaluationReport,
    EvaluationScope,
    RegressionReport,
    METRIC_VERSION,
    LATENCY_PROTOCOL,
    SearchMode,
)

import click
import yaml

from tools.eval.evaluator import (
    SEARCH_MODES,
    load_golden_queries,
    percentile,
    run_evaluation,
)
from tools.eval.reporter import generate_json_report, generate_markdown_report
from tools.eval import load_thresholds
from tools.eval.provenance import (
    comparison_differences,
    current_latency_environment,
    fingerprint,
)
from tools.eval.regression import compare_results, load_baseline

DEFAULT_SUITE = Path("tests/fixtures/eval_battle_royale.yaml")
DEFAULT_OUTPUT_DIR = Path("docs/benchmarks/retrieval_battle_royale")


@dataclass(frozen=True)
class BattleKnowledgeBase:
    """A fixture KB and its matching golden set."""

    kb_id: str
    name: str
    kb_path: Path
    golden_queries_path: Path
    include_stress: bool


class SuiteKnowledgeBase(EvalModel):
    id: Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]+$")]
    name: str = ""
    kb_path: str
    golden_queries: str
    include_stress: bool = False


class BattleSuite(EvalModel):
    version: Literal["1.0"] = "1.0"
    description: str = ""
    modes: list[SearchMode] = Field(default_factory=lambda: list(SEARCH_MODES))
    knowledge_bases: list[SuiteKnowledgeBase] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_entries(self) -> Self:
        ids = [kb.id for kb in self.knowledge_bases]
        if len(ids) != len(set(ids)):
            raise ValueError("knowledge base IDs must be unique")
        if not self.modes or len(self.modes) != len(set(self.modes)):
            raise ValueError("suite modes must be nonempty and unique")
        return self


class ModeSummary(TypedDict):
    mode: str
    knowledge_bases: int
    queries: int
    hit_at_1: float
    hit_at_5: float
    mrr: float
    p50_ms: float
    p95_ms: float
    failure_buckets: dict[str, int]
    adaptive_fallback_rate: float | None


class KnowledgeBaseSummary(TypedDict):
    kb_id: str
    kb_name: str
    mode: str
    queries: int
    hit_at_1: float
    hit_at_5: float
    mrr: float
    p50_ms: float
    p95_ms: float
    adaptive_fallback_rate: float | None


class KnowledgeBaseInfo(TypedDict):
    id: str
    name: str
    kb_path: str
    golden_queries: str
    include_stress: bool


class BattleSummary(TypedDict):
    label: str
    suite: str
    description: str
    judging: str
    modes: list[str]
    knowledge_bases: list[KnowledgeBaseInfo]
    aggregate_by_mode: dict[str, ModeSummary]
    by_kb: list[KnowledgeBaseSummary]
    manifests: dict[str, dict[str, EvaluationManifest]]
    reports: NotRequired[dict[str, dict[str, dict[str, str]]]]
    comparisons: NotRequired[dict[str, dict[str, RegressionReport]]]
    comparison_failures: NotRequired[list[str]]


def load_suite(path: Path) -> tuple[str, list[BattleKnowledgeBase], tuple[str, ...]]:
    """Validate the whole suite before loading any index or model."""
    try:
        suite = BattleSuite.model_validate(
            yaml.safe_load(path.read_text(encoding="utf-8"))
        )
        kbs: list[BattleKnowledgeBase] = []
        for item in suite.knowledge_bases:
            kb_path = (path.parent / item.kb_path).resolve()
            golden_path = (path.parent / item.golden_queries).resolve()
            if not kb_path.is_dir():
                raise ValueError(f"KB path does not exist: {kb_path}")
            load_golden_queries(
                golden_queries_path=golden_path, include_stress=item.include_stress
            )
            kbs.append(
                BattleKnowledgeBase(
                    kb_id=item.id,
                    name=item.name or item.id,
                    kb_path=kb_path,
                    golden_queries_path=golden_path,
                    include_stress=item.include_stress,
                )
            )
        return suite.description, kbs, tuple(suite.modes)
    except (ValueError, OSError, yaml.YAMLError) as error:
        raise click.ClickException(str(error)) from error


def load_battle_baselines(
    baseline_dir: Path,
    kbs: list[BattleKnowledgeBase],
    modes: tuple[str, ...],
    *,
    top_k: int,
    compare_latency: bool,
) -> dict[tuple[str, str], EvaluationReport]:
    """Validate the inventory and selected input identities before loading a model."""
    from trace_search.config import get_settings
    from trace_search.indexing.index_metadata import collect_source_files

    names = {
        f"{kb.kb_id}_{mode}.json": (kb.kb_id, mode)
        for kb in kbs
        for mode in SEARCH_MODES
    }
    inventory: dict[tuple[str, str], EvaluationReport] = {}
    for path in sorted(baseline_dir.glob("*.json")):
        if path.name not in names:
            raise ValueError(f"Unknown battle baseline: {path.name}")
        key: tuple[str, str] = names[path.name]
        try:
            report = load_baseline(path)
            if report.manifest is None:
                raise ValueError("baseline requires evaluation provenance")
            if report.search_mode != key[1]:
                raise ValueError("report mode does not match its filename")
        except (ValueError, OSError) as error:
            raise ValueError(f"Invalid battle baseline {path.name}: {error}") from error
        inventory[key] = report
    required = [(kb.kb_id, mode) for kb in kbs for mode in modes]
    missing = [
        f"{kb_id}_{mode}.json"
        for kb_id, mode in required
        if (kb_id, mode) not in inventory
    ]
    if missing:
        raise ValueError("Missing battle baselines: " + ", ".join(missing))

    config = get_settings()
    min_keywords = load_thresholds()["keyword_match"]["min_keywords"]
    selected: dict[tuple[str, str], EvaluationReport] = {}
    for kb in kbs:
        queries = load_golden_queries(
            golden_queries_path=kb.golden_queries_path, include_stress=kb.include_stress
        )
        corpus = sorted(
            (record.path, record.content_sha)
            for record in collect_source_files(kb.kb_path, config=config)
        )
        for mode in modes:
            key = kb.kb_id, mode
            report = inventory[key]
            assert report.manifest is not None
            # Only input fields are known before construction. Actual reports verify the built recipe later.
            known_inputs = report.manifest.model_copy(
                update={
                    "corpus_fingerprint": fingerprint(corpus),
                    "queryset_fingerprint": fingerprint(
                        [query.to_dict() for query in queries]
                    ),
                    "selected_query_ids": [query.id for query in queries],
                    "scope": EvaluationScope(include_stress=kb.include_stress),
                    "includes_stress_queries": any(
                        query.stress_set for query in queries
                    ),
                    "metric_version": METRIC_VERSION,
                    "latency_protocol": LATENCY_PROTOCOL,
                    "latency_environment": current_latency_environment(),
                    "top_k": top_k,
                    "min_keywords": min_keywords,
                    "strict_keywords": False,
                    "strict_keywords_top1": False,
                }
            )
            try:
                comparison_differences(
                    known_inputs, report.manifest, compare_latency=compare_latency
                )
            except ValueError as error:
                raise ValueError(
                    f"Incompatible battle baseline {kb.kb_id}/{mode}: {error}"
                ) from error
            selected[key] = report
    return selected


def _write_mode_report(
    report: EvaluationReport, output_dir: Path, kb_id: str, mode: str
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    base = f"{kb_id}_{mode}"
    json_path = output_dir / f"{base}.json"
    md_path = output_dir / f"{base}.md"
    json_path.write_text(generate_json_report(report), encoding="utf-8")
    md_path.write_text(generate_markdown_report(report), encoding="utf-8")
    return {"json": _display_path(json_path), "md": _display_path(md_path)}


def _display_path(path: Path) -> str:
    """Show repo-local paths in committed reports when possible."""
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(Path.cwd().resolve()))
    except ValueError:
        return resolved.name


def _failure_buckets(reports: list[EvaluationReport]) -> dict[str, int]:
    buckets: Counter[str] = Counter()
    for report in reports:
        for result in report.results:
            if result.top_1_path_hit:
                continue
            buckets[result.category or "unknown"] += 1
    return dict(sorted(buckets.items()))


def _aggregate_mode(mode: str, reports: list[EvaluationReport]) -> ModeSummary:
    results = [result for report in reports for result in report.results]
    total = len(results)
    latencies = sorted(result.latency_ms for result in results)
    adaptive_flags = [
        result.adaptive_fallback_used
        for result in results
        if result.adaptive_fallback_used is not None
    ]
    return {
        "mode": mode,
        "knowledge_bases": len(reports),
        "queries": total,
        "hit_at_1": (
            sum(1 for result in results if result.top_1_path_hit) / total
            if total
            else 0.0
        ),
        "hit_at_5": (
            sum(1 for result in results if result.top_5_path_hit) / total
            if total
            else 0.0
        ),
        "mrr": (
            statistics.mean(result.path_reciprocal_rank for result in results)
            if results
            else 0.0
        ),
        "p50_ms": percentile(latencies, 50),
        "p95_ms": percentile(latencies, 95),
        "failure_buckets": _failure_buckets(reports),
        "adaptive_fallback_rate": (
            sum(1 for flag in adaptive_flags if flag) / len(adaptive_flags)
            if adaptive_flags
            else None
        ),
    }


def _summary_json(
    *,
    suite_path: Path,
    description: str,
    label: str,
    reports_by_kb_mode: dict[tuple[str, str], EvaluationReport],
    saved_reports: dict[str, dict[str, dict[str, str]]],
    modes: tuple[str, ...],
    kbs: list[BattleKnowledgeBase],
    comparison_failures: list[str] | None = None,
) -> BattleSummary:
    by_mode = {}
    for mode in modes:
        reports = [reports_by_kb_mode[(kb.kb_id, mode)] for kb in kbs]
        by_mode[mode] = _aggregate_mode(mode, reports)

    by_kb: list[KnowledgeBaseSummary] = []
    for kb in kbs:
        for mode in modes:
            report = reports_by_kb_mode[(kb.kb_id, mode)]
            by_kb.append(
                {
                    "kb_id": kb.kb_id,
                    "kb_name": kb.name,
                    "mode": mode,
                    "queries": report.total_queries,
                    "hit_at_1": report.top_1_path_accuracy,
                    "hit_at_5": report.top_5_path_accuracy,
                    "mrr": report.mean_reciprocal_rank,
                    "p50_ms": report.latency_p50_ms,
                    "p95_ms": report.latency_p95_ms,
                    "adaptive_fallback_rate": report.adaptive_fallback_rate,
                }
            )

    manifests: dict[str, dict[str, EvaluationManifest]] = {}
    for kb in kbs:
        manifests[kb.kb_id] = {}
        for mode in modes:
            manifest = reports_by_kb_mode[(kb.kb_id, mode)].manifest
            if manifest is None:
                raise ValueError("Battle reports require evaluation provenance")
            manifests[kb.kb_id][mode] = manifest

    summary: BattleSummary = {
        "label": label,
        "suite": _display_path(suite_path),
        "description": description,
        "judging": "deterministic expected-path metrics only; no LLM judges",
        "modes": list(modes),
        "knowledge_bases": [
            {
                "id": kb.kb_id,
                "name": kb.name,
                "kb_path": _display_path(kb.kb_path),
                "golden_queries": _display_path(kb.golden_queries_path),
                "include_stress": kb.include_stress,
            }
            for kb in kbs
        ],
        "aggregate_by_mode": by_mode,
        "by_kb": by_kb,
        "manifests": manifests,
    }
    if comparison_failures is not None:
        summary["comparison_failures"] = comparison_failures
        summary["comparisons"] = {
            kb.kb_id: {
                mode: regression
                for mode in modes
                if (regression := reports_by_kb_mode[kb.kb_id, mode].regression)
                is not None
            }
            for kb in kbs
        }
    if saved_reports:
        summary["reports"] = saved_reports
    return summary


def _pct(value: float) -> str:
    return f"{value:.1%}"


def _summary_markdown(summary: BattleSummary) -> str:
    mode_rows = []
    by_mode = summary["aggregate_by_mode"]
    for mode in summary["modes"]:
        row = by_mode[mode]
        failure_buckets = row["failure_buckets"] or {}
        failures = ", ".join(f"{k}: {v}" for k, v in failure_buckets.items()) or "-"
        fallback = row.get("adaptive_fallback_rate")
        fallback_text = "-" if fallback is None else _pct(float(fallback))
        mode_rows.append(
            "| {mode} | {queries} | {hit1} | {hit5} | {mrr:.3f} | "
            "{p50:.1f} | {p95:.1f} | {fallback} | {failures} |".format(
                mode=mode,
                queries=row["queries"],
                hit1=_pct(float(row["hit_at_1"])),
                hit5=_pct(float(row["hit_at_5"])),
                mrr=float(row["mrr"]),
                p50=float(row["p50_ms"]),
                p95=float(row["p95_ms"]),
                fallback=fallback_text,
                failures=failures,
            )
        )

    kb_rows = []
    for kb_row in summary["by_kb"]:
        fallback = kb_row.get("adaptive_fallback_rate")
        fallback_text = "-" if fallback is None else _pct(float(fallback))
        kb_rows.append(
            "| {kb} | {mode} | {queries} | {hit1} | {hit5} | {mrr:.3f} | "
            "{p50:.1f} | {p95:.1f} | {fallback} |".format(
                kb=kb_row["kb_id"],
                mode=kb_row["mode"],
                queries=kb_row["queries"],
                hit1=_pct(float(kb_row["hit_at_1"])),
                hit5=_pct(float(kb_row["hit_at_5"])),
                mrr=float(kb_row["mrr"]),
                p50=float(kb_row["p50_ms"]),
                p95=float(kb_row["p95_ms"]),
                fallback=fallback_text,
            )
        )

    lines = [
        "# Retrieval Battle Royale Evaluation",
        "",
        f"**Label:** {summary['label']}",
        f"**Suite:** `{summary['suite']}`",
        f"**Judging:** {summary['judging']}",
        "",
        "## Aggregate by Mode",
        "",
        "| Mode | Queries | Hit@1 | Hit@5 | MRR | p50 ms | p95 ms | Adaptive fallback | Top-1 failure buckets |",
        "|------|---------|-------|-------|-----|--------|--------|----------------|-----------------------|",
        *mode_rows,
        "",
        "## By Knowledge Base",
        "",
        "| KB | Mode | Queries | Hit@1 | Hit@5 | MRR | p50 ms | p95 ms | Adaptive fallback |",
        "|----|------|---------|-------|-------|-----|--------|--------|----------------|",
        *kb_rows,
        "",
        "## Knowledge Bases",
        "",
    ]
    for kb in summary["knowledge_bases"]:
        lines.append(
            f"- **{kb['id']}**: `{kb['kb_path']}` with `{kb['golden_queries']}`"
        )
    if "comparison_failures" in summary:
        gate_failures = summary["comparison_failures"]
        lines.extend(
            ["", "## Comparative gate", "", "FAIL" if gate_failures else "PASS"]
        )
        lines.extend(f"- {failure}" for failure in gate_failures)
    lines.append("")
    return "\n".join(lines)


@click.command()
@click.option(
    "--suite",
    type=click.Path(exists=True, path_type=Path),
    default=DEFAULT_SUITE,
    show_default=True,
    help="YAML file listing fixture KBs and golden sets.",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=DEFAULT_OUTPUT_DIR,
    show_default=True,
    help="Directory for summary reports.",
)
@click.option(
    "--label",
    default="run",
    show_default=True,
    help="Run label used as an output subdirectory.",
)
@click.option(
    "--mode",
    "requested_modes",
    multiple=True,
    type=click.Choice(SEARCH_MODES),
    help="Limit to one or more modes. Defaults to suite modes.",
)
@click.option(
    "--top-k",
    type=click.IntRange(min=1),
    default=5,
    show_default=True,
    help="Results per query.",
)
@click.option(
    "--baseline-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Directory of KB_MODE.json reports for comparative quality gates.",
)
@click.option(
    "--quality-only",
    is_flag=True,
    help="Exclude baseline latency regression for cross-host quality comparisons.",
)
@click.option(
    "--detail-reports",
    is_flag=True,
    help="Also write per-KB/per-mode JSON and Markdown reports.",
)
def main(
    suite: Path,
    output_dir: Path,
    label: str,
    requested_modes: tuple[str, ...],
    top_k: int,
    detail_reports: bool,
    baseline_dir: Path | None,
    quality_only: bool,
) -> None:
    """Run the committed multi-KB retrieval battle suite."""
    try:
        _run(
            suite,
            output_dir,
            label,
            requested_modes,
            top_k,
            detail_reports,
            baseline_dir,
            quality_only,
        )
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from error


def _run(
    suite: Path,
    output_dir: Path,
    label: str,
    requested_modes: tuple[str, ...],
    top_k: int,
    detail_reports: bool,
    baseline_dir: Path | None,
    quality_only: bool,
) -> None:
    if Path(label).name != label or label in (".", ".."):
        raise click.BadParameter(
            "label must be a single directory name", param_hint="--label"
        )
    if quality_only and baseline_dir is None:
        raise click.UsageError("--quality-only requires --baseline-dir")
    if len(requested_modes) != len(set(requested_modes)):
        raise click.UsageError("Search modes must be unique")
    description, kbs, suite_modes = load_suite(suite)
    modes = requested_modes or suite_modes
    run_dir = output_dir / label
    baselines = (
        load_battle_baselines(
            baseline_dir,
            kbs,
            tuple(modes),
            top_k=top_k,
            compare_latency=not quality_only,
        )
        if baseline_dir is not None
        else {}
    )
    comparison_failures: list[str] = []

    from trace_search.indexing.embeddings import build_embedding_backend
    from trace_search.indexing.wiki_indexer import WikiIndexer
    from trace_search.retrieval.search import SemanticSearch
    from trace_search.indexing.embedding_warmup import warm_embedding_model

    reports_by_kb_mode = {}
    saved_reports: dict[str, dict[str, dict[str, str]]] = {}

    with tempfile.TemporaryDirectory(prefix="trace-battle-") as tmp:
        tmp_root = Path(tmp)
        backend = build_embedding_backend()
        warm_embedding_model(backend)

        for kb in kbs:
            click.echo(f"Indexing {kb.kb_id}: {kb.kb_path}")
            indexer = WikiIndexer(
                kb_path=kb.kb_path,
                index_root=tmp_root / kb.kb_id,
                backend=backend,
            )
            indexer.build_index(force=True)

            for mode in modes:
                SemanticSearch._embedding_cache.clear()
                click.echo(f"Evaluating {kb.kb_id} / {mode}")
                report = run_evaluation(
                    indexer=indexer,
                    search_mode=mode,
                    quick_only=False,
                    top_k=top_k,
                    stress_only=False,
                    include_stress=kb.include_stress,
                    golden_queries_path=kb.golden_queries_path,
                )
                reports_by_kb_mode[(kb.kb_id, mode)] = report
                if baseline_dir is not None:
                    baseline = baselines[kb.kb_id, mode]
                    try:
                        report.regression = compare_results(
                            report, baseline, compare_latency=not quality_only
                        )
                    except ValueError as error:
                        comparison_failures.append(
                            f"{kb.kb_id}/{mode}: comparison failed: {error}"
                        )
                    else:
                        if report.regression.has_regression:
                            comparison_failures.append(
                                f"{kb.kb_id}/{mode}: regression, Top-1 delta {report.regression.top_1_delta:+.1%}, Top-5 delta {report.regression.top_5_delta:+.1%}, latency p95 delta {report.regression.latency_delta_pct:+.0%}"
                            )
                            for previous, current in zip(
                                baseline.results, report.results, strict=True
                            ):
                                lost = []
                                if (
                                    previous.top_1_path_hit
                                    and not current.top_1_path_hit
                                ):
                                    lost.append("Top-1")
                                if (
                                    previous.top_5_path_hit
                                    and not current.top_5_path_hit
                                ):
                                    lost.append("Top-5")
                                if lost:
                                    comparison_failures.append(
                                        f"{kb.kb_id}/{mode} query {current.query_id}: lost {', '.join(lost)}, {previous.retrieved_path} -> {current.retrieved_path}"
                                    )
                if detail_reports or baseline_dir is not None:
                    saved_reports.setdefault(kb.kb_id, {})[mode] = _write_mode_report(
                        report, run_dir, kb.kb_id, mode
                    )

    summary = _summary_json(
        suite_path=suite,
        description=description,
        label=label,
        reports_by_kb_mode=reports_by_kb_mode,
        saved_reports=saved_reports,
        modes=tuple(modes),
        kbs=kbs,
        comparison_failures=comparison_failures if baseline_dir is not None else None,
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    summary_json = run_dir / "summary.json"
    summary_md = run_dir / "summary.md"
    summary_json.write_text(
        TypeAdapter(BattleSummary).dump_json(summary, indent=2).decode(),
        encoding="utf-8",
    )
    summary_md.write_text(_summary_markdown(summary), encoding="utf-8")
    click.echo(f"Summary: {summary_md}")
    if comparison_failures:
        raise click.ClickException(
            "Battle comparison failed:\n" + "\n".join(comparison_failures)
        )
    if baseline_dir is not None:
        click.echo("Battle comparison: all KB/mode gates passed")


if __name__ == "__main__":
    main()
