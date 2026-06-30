"""Self-diagnosis helpers for Trace configuration, corpus, and indexes."""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trace_search.config import settings
from trace_search.indexing.index_metadata import (
    INDEX_METADATA_VERSION,
    IndexMetadata,
    SourceChangeSet,
    categorize_source_changes,
    metadata_matches_active_model,
    metadata_path,
    read_index_metadata,
)
from trace_search.extraction.corpus import iter_kb_files
from trace_search.indexing.index_paths import bm25_dir, chroma_dir
from trace_search.indexing.kb_paths import get_default_index_root, should_exclude_path

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
    metadata_version: int | None = None
    metadata_version_current: int = INDEX_METADATA_VERSION
    next_reindex: str = "forced"
    changes: SourceChangeSet | None = None


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
    visible_paths = {p for p in iter_kb_files(kb_path)}
    for path in kb_path.rglob("*"):
        if not path.is_file():
            continue
        if path in visible_paths:
            scan.visible_by_extension[path.suffix.lower()] += 1
            continue
        if should_exclude_path(path, kb_path):
            scan.excluded_by_reason[_exclusion_reason(path, kb_path)] += 1
    return scan


def _read_metadata_version(index_path: Path) -> int | None:
    """Best-effort raw read of the persisted metadata schema version."""
    path = metadata_path(index_path)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return int(raw.get("version", 0))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _missing_index_diagnosis(
    index_path: Path,
    *,
    chroma_path: Path,
    bm25_path: Path,
) -> IndexDiagnosis | None:
    missing = []
    if not chroma_path.exists():
        missing.append("ChromaDB")
    if not bm25_path.exists():
        missing.append("BM25")
    if not missing:
        return None

    return IndexDiagnosis(
        status="missing",
        messages=[
            f"Missing {' and '.join(missing)} index files.",
            "Run `reindex` after confirming the corpus path.",
        ],
        last_index_time=None,
        metadata_version=_read_metadata_version(index_path),
        next_reindex="forced",
        changes=None,
    )


def _unknown_metadata_diagnosis(raw_version: int | None) -> IndexDiagnosis:
    if raw_version is not None and raw_version != INDEX_METADATA_VERSION:
        reason_msg = (
            f"Index metadata is at schema v{raw_version}; "
            f"current schema is v{INDEX_METADATA_VERSION}."
        )
        next_msg = "Next `reindex` will be forced (schema upgrade)."
    else:
        reason_msg = "Index exists but has no readable Trace metadata."
        next_msg = "Next `reindex` will be forced (no metadata)."

    return IndexDiagnosis(
        status="unknown",
        messages=[reason_msg, next_msg],
        last_index_time=None,
        metadata_version=raw_version,
        next_reindex="forced",
        changes=None,
    )


def _freshness_diagnosis(kb_path: Path, metadata: IndexMetadata) -> IndexDiagnosis:
    messages: list[str] = []
    status = "healthy"

    if not metadata_matches_active_model(metadata):
        status = "incompatible"
        messages.append(
            "Index metadata does not match the active embedding model/backend."
        )

    changes = categorize_source_changes(kb_path, metadata)
    if changes.has_changes:
        status = "stale" if status == "healthy" else status
        messages.append(
            f"{len(changes.added)} added, {len(changes.changed)} changed, "
            f"{len(changes.removed)} removed since last index."
        )
        if status == "incompatible":
            messages.append("Next `reindex` will be forced because the model changed.")
            next_reindex = "forced"
        else:
            messages.append("Next `reindex` will run incrementally on changed files.")
            next_reindex = "incremental"
    elif status == "incompatible":
        messages.append("Next `reindex` will run, but model mismatch forces a rebuild.")
        next_reindex = "forced"
    else:
        messages.append("Indexes are present, compatible, and fresh.")
        next_reindex = "incremental"

    return IndexDiagnosis(
        status=status,
        messages=messages,
        last_index_time=metadata.build_completed_at or None,
        metadata_version=metadata.version,
        next_reindex=next_reindex,
        changes=changes,
    )


def diagnose_index(kb_path: Path, index_path: Path) -> IndexDiagnosis:
    """Diagnose index presence, compatibility, freshness, and last build time."""
    model_slug = settings.model_slug
    chroma_path = chroma_dir(index_path, model_slug)
    bm25_path = bm25_dir(index_path, model_slug)

    missing = _missing_index_diagnosis(
        index_path,
        chroma_path=chroma_path,
        bm25_path=bm25_path,
    )
    if missing is not None:
        return missing

    raw_version = _read_metadata_version(index_path)
    metadata = read_index_metadata(index_path)
    if metadata is None:
        return _unknown_metadata_diagnosis(raw_version)
    return _freshness_diagnosis(kb_path, metadata)


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


def _metadata_version_label(index: IndexDiagnosis) -> str:
    version = index.metadata_version
    current = index.metadata_version_current
    if version is None:
        return "none"
    if version == current:
        return f"v{version}"
    return f"v{version} (current: v{current})"


def _append_collection_report(
    lines: list[str],
    collection: CollectionDiagnosis,
) -> None:
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
    lines.append(
        f"- **Last index time:** {collection.index.last_index_time or 'unknown'}"
    )
    lines.append(f"- **Metadata schema:** {_metadata_version_label(collection.index)}")
    lines.append(f"- **Next reindex:** {collection.index.next_reindex}")

    changes = collection.index.changes
    if changes is not None:
        lines.append(
            "- **Source changes since last index:** "
            f"unchanged={len(changes.unchanged)}, "
            f"added={len(changes.added)}, "
            f"changed={len(changes.changed)}, "
            f"removed={len(changes.removed)}"
        )


def _append_filter_hint(lines: list[str]) -> None:
    lines.append("")
    lines.append("## Filters")
    lines.append(
        "- Scope any search or `list_documents` call with `path_prefix`, "
        "`extensions`, or `since` (ISO 8601 datetime). "
        "Example: `search('router', path_prefix='architecture/', extensions=['.md'])`."
    )


def _append_probe_report(lines: list[str], probe: ProbeDiagnosis) -> None:
    lines.append("")
    lines.append("## Sample Query")
    lines.append(f"- **Query:** `{probe.query}`")
    lines.append(f"- **Status:** {probe.status}")
    if probe.elapsed_ms is not None:
        lines.append(f"- **Latency:** {probe.elapsed_ms:.1f} ms")
    lines.append(f"- **Results:** {probe.result_count}")
    if probe.top_result:
        lines.append(f"- **Top result:** {probe.top_result}")
    if probe.message:
        lines.append(f"- **Note:** {probe.message}")


def render_doctor_report(report: DoctorReport) -> str:
    """Render a doctor report as Markdown."""
    lines = ["# Trace Doctor", ""]
    status = "valid" if report.config_valid else "invalid"
    lines.append(f"- **Configuration:** {status}")
    lines.append(f"- **Message:** {report.config_message}")

    if not report.collections:
        return "\n".join(lines)

    for collection in report.collections:
        _append_collection_report(lines, collection)

    _append_filter_hint(lines)

    if report.probe is not None:
        _append_probe_report(lines, report.probe)

    return "\n".join(lines)
