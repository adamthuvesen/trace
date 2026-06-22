#!/usr/bin/env python3
"""Run retrieval evaluations across multiple committed fixture knowledge bases."""

from __future__ import annotations

import json
import statistics
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import click
import yaml

from tools.eval.evaluator import percentile, run_evaluation
from tools.eval.reporter import generate_json_report, generate_markdown_report

SEARCH_MODES = ("bm25", "semantic", "hybrid", "reranked", "smart")
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


def load_suite(path: Path) -> tuple[str, list[BattleKnowledgeBase], tuple[str, ...]]:
    """Load the battle suite YAML, resolving fixture paths relative to the file."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise click.ClickException(f"{path} must contain a YAML mapping")

    suite_root = path.parent
    raw_kbs = data.get("knowledge_bases")
    if not isinstance(raw_kbs, list) or not raw_kbs:
        raise click.ClickException(f"{path} must define at least one knowledge base")

    kbs: list[BattleKnowledgeBase] = []
    for item in raw_kbs:
        kb_path = (suite_root / item["kb_path"]).resolve()
        golden_path = (suite_root / item["golden_queries"]).resolve()
        if not kb_path.is_dir():
            raise click.ClickException(f"KB path does not exist: {kb_path}")
        if not golden_path.is_file():
            raise click.ClickException(
                f"Golden queries file does not exist: {golden_path}"
            )
        kbs.append(
            BattleKnowledgeBase(
                kb_id=str(item["id"]),
                name=str(item.get("name", item["id"])),
                kb_path=kb_path,
                golden_queries_path=golden_path,
                include_stress=bool(item.get("include_stress", False)),
            )
        )

    raw_modes = data.get("modes", SEARCH_MODES)
    modes = tuple(str(mode) for mode in raw_modes)
    unknown = sorted(set(modes) - set(SEARCH_MODES))
    if unknown:
        raise click.ClickException(
            f"Unknown search modes in {path}: {', '.join(unknown)}"
        )

    return str(data.get("description", "")), kbs, modes


def _write_mode_report(
    report, output_dir: Path, kb_id: str, mode: str
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    base = f"{kb_id}_{mode}"
    json_path = output_dir / f"{base}.json"
    md_path = output_dir / f"{base}.md"
    json_path.write_text(generate_json_report(report), encoding="utf-8")
    md_path.write_text(generate_markdown_report(report), encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}


def _display_path(path: Path) -> str:
    """Show repo-local paths in committed reports when possible."""
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(resolved)


def _failure_buckets(reports) -> dict[str, int]:
    buckets: Counter[str] = Counter()
    for report in reports:
        for result in report.results:
            if result.top_1_path_hit:
                continue
            buckets[result.category or "unknown"] += 1
    return dict(sorted(buckets.items()))


def _aggregate_mode(mode: str, reports) -> dict[str, object]:
    results = [result for report in reports for result in report.results]
    total = len(results)
    latencies = sorted(result.latency_ms for result in results)
    smart_flags = [
        result.smart_fallback_used
        for result in results
        if result.smart_fallback_used is not None
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
        "smart_fallback_rate": (
            sum(1 for flag in smart_flags if flag) / len(smart_flags)
            if smart_flags
            else None
        ),
    }


def _summary_json(
    *,
    suite_path: Path,
    description: str,
    label: str,
    reports_by_kb_mode: dict[tuple[str, str], object],
    saved_reports: dict[str, dict[str, dict[str, str]]],
    modes: tuple[str, ...],
    kbs: list[BattleKnowledgeBase],
) -> dict[str, object]:
    by_mode = {}
    for mode in modes:
        reports = [reports_by_kb_mode[(kb.kb_id, mode)] for kb in kbs]
        by_mode[mode] = _aggregate_mode(mode, reports)

    by_kb = []
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
                    "smart_fallback_rate": report.smart_fallback_rate,
                }
            )

    summary: dict[str, object] = {
        "label": label,
        "suite": str(suite_path),
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
    }
    if saved_reports:
        summary["reports"] = saved_reports
    return summary


def _pct(value: float) -> str:
    return f"{value:.1%}"


def _summary_markdown(summary: dict[str, object]) -> str:
    mode_rows = []
    by_mode = summary["aggregate_by_mode"]
    for mode in summary["modes"]:
        row = by_mode[mode]
        failure_buckets = row["failure_buckets"] or {}
        failures = ", ".join(f"{k}: {v}" for k, v in failure_buckets.items()) or "-"
        fallback = row.get("smart_fallback_rate")
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
    for row in summary["by_kb"]:
        fallback = row.get("smart_fallback_rate")
        fallback_text = "-" if fallback is None else _pct(float(fallback))
        kb_rows.append(
            "| {kb} | {mode} | {queries} | {hit1} | {hit5} | {mrr:.3f} | "
            "{p50:.1f} | {p95:.1f} | {fallback} |".format(
                kb=row["kb_id"],
                mode=row["mode"],
                queries=row["queries"],
                hit1=_pct(float(row["hit_at_1"])),
                hit5=_pct(float(row["hit_at_5"])),
                mrr=float(row["mrr"]),
                p50=float(row["p50_ms"]),
                p95=float(row["p95_ms"]),
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
        "| Mode | Queries | Hit@1 | Hit@5 | MRR | p50 ms | p95 ms | Smart fallback | Top-1 failure buckets |",
        "|------|---------|-------|-------|-----|--------|--------|----------------|-----------------------|",
        *mode_rows,
        "",
        "## By Knowledge Base",
        "",
        "| KB | Mode | Queries | Hit@1 | Hit@5 | MRR | p50 ms | p95 ms | Smart fallback |",
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
@click.option("--top-k", default=5, show_default=True, help="Results per query.")
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
) -> None:
    """Run the committed multi-KB retrieval battle suite."""
    description, kbs, suite_modes = load_suite(suite)
    modes = requested_modes or suite_modes
    run_dir = output_dir / label

    from trace_search.indexing.embeddings import build_embedding_backend
    from trace_search.indexing.wiki_indexer import WikiIndexer
    from trace_search.retrieval.search import SemanticSearch
    from trace_search.server.server_warmup import warm_embedding_model

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
                chroma_path=tmp_root / kb.kb_id / "chroma",
                bm25_path=tmp_root / kb.kb_id / "bm25",
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
                if detail_reports:
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
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    summary_json = run_dir / "summary.json"
    summary_md = run_dir / "summary.md"
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    summary_md.write_text(_summary_markdown(summary), encoding="utf-8")
    click.echo(f"Summary: {summary_md}")


if __name__ == "__main__":
    main()
