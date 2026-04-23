"""Self-diagnosis helpers for Trace configuration, corpus, and indexes."""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trace_search.config import settings
from trace_search.index_metadata import (
    metadata_matches_active_model,
    read_index_metadata,
    stale_source_paths,
)
from trace_search.indexer import (
    SUPPORTED_EXTENSIONS,
    get_default_index_root,
    should_exclude_path,
)

SampleQueryRunner = Callable[[str, str | None], list[dict[str, Any]]]


@dataclass
class CorpusScan:
    """Visible and excluded corpus counts for one collection."""

    visible_by_extension: Counter[str] = field(default_factory=Counter)
    excluded_by_reason: Counter[str] = field(default_factory=Counter)

    @property
    def visible_total(self) -> int:
        return sum(self.visible_by_extension.values())


@dataclass
class IndexDiagnosis:
    """Index health summary for one collection."""

    status: str
    messages: list[str]
    last_index_time: str | None


@dataclass
class CollectionDiagnosis:
    """Doctor details for one collection."""

    name: str
    kb_path: Path
    index_path: Path
    corpus: CorpusScan
    index: IndexDiagnosis


@dataclass
class ProbeDiagnosis:
    """Optional sample-query probe result."""

    query: str
    status: str
    elapsed_ms: float | None = None
    result_count: int = 0
    top_result: str | None = None
    message: str | None = None


@dataclass
class DoctorReport:
    """Complete doctor report."""

    config_valid: bool
    config_message: str
    collections: list[CollectionDiagnosis]
    probe: ProbeDiagnosis | None = None

    @property
    def ok(self) -> bool:
        return self.config_valid


def invalid_config_report(message: str) -> DoctorReport:
    """Create a report for configuration failures that prevented scanning."""
    return DoctorReport(
        config_valid=False,
        config_message=message,
        collections=[],
    )


def _exclusion_reason(path: Path, kb_path: Path) -> str:
    rel_parts = path.relative_to(kb_path).parts
    excluded = set(settings.exclude_patterns_list)
    for part in rel_parts:
        if part.startswith("."):
            return "hidden path"
        if part in excluded:
            return f"exclude pattern: {part}"
    return "excluded"


def scan_corpus(kb_path: Path) -> CorpusScan:
    """Scan a collection for visible supported files and excluded paths."""
    scan = CorpusScan()
    for path in kb_path.rglob("*"):
        if should_exclude_path(path, kb_path):
            scan.excluded_by_reason[_exclusion_reason(path, kb_path)] += 1
            continue
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext in SUPPORTED_EXTENSIONS:
            scan.visible_by_extension[ext] += 1
    return scan


def diagnose_index(kb_path: Path, index_path: Path) -> IndexDiagnosis:
    """Diagnose index presence, compatibility, freshness, and last build time."""
    model_slug = settings.model_slug
    chroma_path = index_path / f".chroma_db_{model_slug}"
    bm25_path = index_path / f".bm25_index_{model_slug}"

    messages: list[str] = []
    status = "healthy"

    if not chroma_path.exists() or not bm25_path.exists():
        missing = []
        if not chroma_path.exists():
            missing.append("ChromaDB")
        if not bm25_path.exists():
            missing.append("BM25")
        return IndexDiagnosis(
            status="missing",
            messages=[
                f"Missing {' and '.join(missing)} index files.",
                "Run `reindex` after confirming the corpus path.",
            ],
            last_index_time=None,
        )

    metadata = read_index_metadata(index_path)
    if metadata is None:
        return IndexDiagnosis(
            status="unknown",
            messages=[
                "Index exists but has no readable Trace metadata.",
                "Run `reindex` to record model and freshness metadata.",
            ],
            last_index_time=None,
        )

    if not metadata_matches_active_model(metadata):
        status = "incompatible"
        messages.append(
            "Index metadata does not match the active embedding model/backend."
        )

    stale = stale_source_paths(kb_path, metadata)
    if stale:
        status = "stale" if status == "healthy" else status
        messages.append(f"{len(stale)} source file(s) changed since last index.")

    if not messages:
        messages.append("Indexes are present, compatible, and fresh.")

    return IndexDiagnosis(
        status=status,
        messages=messages,
        last_index_time=metadata.build_completed_at or None,
    )


def run_probe(
    query: str,
    collection: str | None,
    runner: SampleQueryRunner,
) -> ProbeDiagnosis:
    """Run a sample query and capture latency plus top-result summary."""
    start = time.perf_counter()
    try:
        results = runner(query, collection)
    except Exception as exc:
        return ProbeDiagnosis(
            query=query,
            status="failed",
            message=str(exc),
        )

    elapsed_ms = (time.perf_counter() - start) * 1000
    top_result = None
    if results:
        top = results[0]
        title = top.get("title") or top.get("path") or "untitled"
        path = top.get("path")
        top_result = f"{title} (`{path}`)" if path else str(title)

    status = "ok" if results else "zero-results"
    return ProbeDiagnosis(
        query=query,
        status=status,
        elapsed_ms=elapsed_ms,
        result_count=len(results),
        top_result=top_result,
        message=None
        if results
        else "No results. Check corpus visibility, index freshness, or try a broader query.",
    )


def diagnose_collections(
    collections: dict[str, Path],
    *,
    index_root: Path | None = None,
    sample_query: str | None = None,
    sample_query_runner: SampleQueryRunner | None = None,
    sample_collection: str | None = None,
) -> DoctorReport:
    """Build a doctor report for resolved collections."""
    idx_root = index_root or (settings.index_path if settings.index_path else None)
    collection_reports: list[CollectionDiagnosis] = []

    for name, kb_path in sorted(collections.items()):
        collection_index = get_default_index_root(
            kb_path,
            idx_root,
            name if idx_root else None,
        )
        collection_reports.append(
            CollectionDiagnosis(
                name=name,
                kb_path=kb_path,
                index_path=collection_index,
                corpus=scan_corpus(kb_path),
                index=diagnose_index(kb_path, collection_index),
            )
        )

    probe = None
    if sample_query and sample_query_runner is not None:
        probe = run_probe(sample_query, sample_collection, sample_query_runner)

    return DoctorReport(
        config_valid=True,
        config_message="Configuration is valid.",
        collections=collection_reports,
        probe=probe,
    )


def render_doctor_report(report: DoctorReport) -> str:
    """Render a doctor report as Markdown."""
    lines = ["# Trace Doctor", ""]
    status = "valid" if report.config_valid else "invalid"
    lines.append(f"- **Configuration:** {status}")
    lines.append(f"- **Message:** {report.config_message}")

    if not report.collections:
        return "\n".join(lines)

    for collection in report.collections:
        lines.append("")
        lines.append(f"## Collection: {collection.name}")
        lines.append(f"- **Knowledge base:** `{collection.kb_path}`")
        lines.append(f"- **Index root:** `{collection.index_path}`")
        lines.append(f"- **Visible supported docs:** {collection.corpus.visible_total}")

        if collection.corpus.visible_by_extension:
            ext_counts = ", ".join(
                f"{ext}={count}"
                for ext, count in sorted(collection.corpus.visible_by_extension.items())
            )
            lines.append(f"- **By extension:** {ext_counts}")
        else:
            lines.append(
                "- **Warning:** No supported visible documents found; search will return no results."
            )

        if collection.corpus.excluded_by_reason:
            excluded = ", ".join(
                f"{reason}={count}"
                for reason, count in sorted(collection.corpus.excluded_by_reason.items())
            )
            lines.append(f"- **Excluded paths:** {excluded}")
        else:
            lines.append("- **Excluded paths:** none")

        lines.append(f"- **Index status:** {collection.index.status}")
        for message in collection.index.messages:
            lines.append(f"  - {message}")
        last_index_time = collection.index.last_index_time or "unknown"
        lines.append(f"- **Last index time:** {last_index_time}")

    if report.probe is not None:
        lines.append("")
        lines.append("## Sample Query")
        lines.append(f"- **Query:** `{report.probe.query}`")
        lines.append(f"- **Status:** {report.probe.status}")
        if report.probe.elapsed_ms is not None:
            lines.append(f"- **Latency:** {report.probe.elapsed_ms:.1f} ms")
        lines.append(f"- **Results:** {report.probe.result_count}")
        if report.probe.top_result:
            lines.append(f"- **Top result:** {report.probe.top_result}")
        if report.probe.message:
            lines.append(f"- **Note:** {report.probe.message}")

    return "\n".join(lines)
