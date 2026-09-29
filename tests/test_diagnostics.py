"""Tests for Trace doctor diagnostics."""

import json
from pathlib import Path

import numpy as np

from trace_search.collections.diagnostics import (
    diagnose_collections,
    diagnose_index,
    invalid_config_report,
    render_doctor_report,
    scan_corpus,
)
from trace_search.config import settings
from trace_search.indexing.index_metadata import (
    IndexMetadata,
    build_index_metadata,
    utc_now_iso,
)
from trace_search.indexing.index_store import (
    IndexSnapshot,
    read_current,
    write_snapshot,
    writer_lock,
)
from trace_search.indexing.kb_paths import get_default_index_root


def _publish_metadata(index_root: Path, metadata: IndexMetadata) -> Path:
    """Publish an empty generation carrying `metadata`; return its metadata file."""
    snapshot = IndexSnapshot.build(
        chunk_ids=[],
        texts=[],
        chunks=[],
        embeddings=np.empty((0, 3), dtype=np.float32),
        k1=settings.bm25_k1,
        b=settings.bm25_b,
        metadata=metadata,
    )
    with writer_lock(index_root):
        published = write_snapshot(index_root, snapshot)
    assert published.generation is not None
    return index_root / published.generation / "index_metadata.json"


def test_invalid_config_report_renders_message():
    report = invalid_config_report("KB_PATH is bad")
    rendered = render_doctor_report(report)

    assert not report.ok
    assert "**Configuration:** invalid" in rendered
    assert "KB_PATH is bad" in rendered


def test_scan_corpus_counts_visible_and_excluded_paths(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "intro.md").write_text("# Intro", encoding="utf-8")
    (kb / "node_modules").mkdir()
    (kb / "node_modules" / "package.md").write_text("# Hidden", encoding="utf-8")
    (kb / ".secret.md").write_text("# Secret", encoding="utf-8")

    scan = scan_corpus(kb)

    assert scan.visible_total == 1
    assert scan.visible_by_extension[".md"] == 1
    assert scan.excluded_by_reason["exclude pattern: node_modules"] >= 1
    assert scan.excluded_by_reason["hidden path"] >= 1


def test_scan_corpus_reports_active_traceignore(tmp_path):
    kb = tmp_path / "kb"
    (kb / "wiki").mkdir(parents=True)
    (kb / "wiki" / "page.md").write_text("# Page", encoding="utf-8")
    (kb / "raw.md").write_text("# Raw", encoding="utf-8")
    (kb / ".traceignore").write_text("/*\n!/wiki/\n", encoding="utf-8")

    scan = scan_corpus(kb)

    assert scan.traceignore_active
    assert scan.visible_total == 1
    assert scan.excluded_by_reason[".traceignore"] == 1


def test_scan_corpus_excludes_outside_symlink(tmp_path):
    kb = tmp_path / "kb"
    outside = tmp_path / "outside"
    kb.mkdir()
    outside.mkdir()
    (kb / "intro.md").write_text("# Intro", encoding="utf-8")
    target = outside / "secret.md"
    target.write_text("# Secret", encoding="utf-8")
    (kb / "secret-link.md").symlink_to(target)

    scan = scan_corpus(kb)

    assert scan.visible_total == 1
    assert scan.visible_by_extension[".md"] == 1
    assert scan.excluded_by_reason["excluded"] >= 1


def test_diagnose_index_reports_missing_indexes(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    diagnosis = diagnose_index(kb, tmp_path / "indexes")

    assert diagnosis.status == "missing"
    assert "Run `reindex`" in "\n".join(diagnosis.messages)


def test_diagnose_index_mentions_legacy_chroma_dirs(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    index_root = tmp_path / "indexes"
    (index_root / ".chroma_db_all_minilm_l6_v2").mkdir(parents=True)

    diagnosis = diagnose_index(kb, index_root)

    assert diagnosis.status == "missing"
    assert ".chroma_db_all_minilm_l6_v2" in "\n".join(diagnosis.messages)


def test_diagnose_index_reports_unknown_without_metadata(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    index_root = tmp_path / "indexes"
    metadata = build_index_metadata(
        kb_path=kb,
        build_started_at=utc_now_iso(),
        build_completed_at=utc_now_iso(),
        document_count=0,
        chunk_count=0,
    )
    _publish_metadata(index_root, metadata).write_text("not json", encoding="utf-8")

    diagnosis = diagnose_index(kb, index_root)

    assert diagnosis.status == "unknown"
    assert diagnosis.last_index_time is None


def test_diagnose_index_reports_fresh_metadata(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "intro.md").write_text("# Intro", encoding="utf-8")
    index_root = get_default_index_root(kb)
    completed = utc_now_iso()
    metadata = build_index_metadata(
        kb_path=kb,
        build_started_at=completed,
        build_completed_at=completed,
        document_count=1,
        chunk_count=1,
    )
    _publish_metadata(index_root, metadata)

    diagnosis = diagnose_index(kb, index_root)

    assert diagnosis.status == "healthy"
    assert diagnosis.last_index_time == completed
    assert diagnosis.next_reindex == "incremental"
    assert diagnosis.changes is not None
    assert len(diagnosis.changes.unchanged) == 1
    assert diagnosis.changes.has_changes is False
    assert diagnosis.metadata_version == diagnosis.metadata_version_current


def test_diagnose_index_reports_categorized_changes(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    keep = kb / "keep.md"
    keep.write_text("# Keep", encoding="utf-8")
    edit = kb / "edit.md"
    edit.write_text("# Edit\n\nold", encoding="utf-8")
    drop = kb / "drop.md"
    drop.write_text("# Drop", encoding="utf-8")
    index_root = get_default_index_root(kb)
    completed = utc_now_iso()
    metadata = build_index_metadata(
        kb_path=kb,
        build_started_at=completed,
        build_completed_at=completed,
        document_count=3,
        chunk_count=3,
    )
    _publish_metadata(index_root, metadata)

    edit.write_text("# Edit\n\nupdated content here", encoding="utf-8")
    drop.unlink()
    (kb / "new.md").write_text("# New", encoding="utf-8")

    diagnosis = diagnose_index(kb, index_root)
    rendered = render_doctor_report(diagnose_collections({"docs": kb}))

    assert diagnosis.status == "stale"
    assert diagnosis.next_reindex == "incremental"
    assert diagnosis.changes is not None
    assert diagnosis.changes.added == ["new.md"]
    assert diagnosis.changes.changed == ["edit.md"]
    assert diagnosis.changes.removed == ["drop.md"]
    assert diagnosis.changes.unchanged == ["keep.md"]
    assert "unchanged=1" in rendered
    assert "added=1" in rendered
    assert "changed=1" in rendered
    assert "removed=1" in rendered
    assert "Next reindex" in rendered


def test_diagnose_index_forces_reindex_when_model_mismatch_has_source_changes(
    tmp_path,
):
    kb = tmp_path / "kb"
    kb.mkdir()
    doc = kb / "intro.md"
    doc.write_text("# Intro", encoding="utf-8")
    index_root = get_default_index_root(kb)
    completed = utc_now_iso()
    metadata = build_index_metadata(
        kb_path=kb,
        build_started_at=completed,
        build_completed_at=completed,
        document_count=1,
        chunk_count=1,
    )
    metadata_file = _publish_metadata(index_root, metadata)
    raw = json.loads(metadata_file.read_text(encoding="utf-8"))
    raw["embedding_model"] = "some-other-model"
    metadata_file.write_text(json.dumps(raw), encoding="utf-8")
    doc.write_text("# Intro\n\nchanged", encoding="utf-8")

    diagnosis = diagnose_index(kb, index_root)

    assert diagnosis.status == "incompatible"
    assert diagnosis.next_reindex == "forced"
    assert any("forced" in msg for msg in diagnosis.messages)


def test_diagnose_index_reports_outdated_metadata_as_forced_rebuild(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "intro.md").write_text("# Intro", encoding="utf-8")
    index_root = get_default_index_root(kb)
    metadata = build_index_metadata(
        kb_path=kb,
        build_started_at=utc_now_iso(),
        build_completed_at=utc_now_iso(),
        document_count=1,
        chunk_count=1,
    )
    metadata_file = _publish_metadata(index_root, metadata)
    raw = json.loads(metadata_file.read_text(encoding="utf-8"))
    raw["version"] = 1
    metadata_file.write_text(json.dumps(raw), encoding="utf-8")

    diagnosis = diagnose_index(kb, index_root)

    assert diagnosis.status == "unknown"
    assert diagnosis.next_reindex == "forced"


def test_diagnose_index_never_indexed_collection(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    diagnosis = diagnose_index(kb, tmp_path / "indexes")

    assert diagnosis.status == "missing"
    assert diagnosis.next_reindex == "forced"
    assert diagnosis.changes is None
    assert diagnosis.metadata_version is None


def test_render_doctor_report_includes_filter_hint(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "intro.md").write_text("# Intro", encoding="utf-8")
    report = diagnose_collections({"docs": kb})
    rendered = render_doctor_report(report)

    assert "## Filters" in rendered
    assert "path_prefix" in rendered
    assert "extensions" in rendered
    assert "since" in rendered


def test_diagnose_collections_runs_sample_query_probe(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "intro.md").write_text("# Intro", encoding="utf-8")

    report = diagnose_collections(
        {"docs": kb},
        sample_query="intro",
        sample_query_runner=lambda query, collection: [
            {"title": "Intro", "path": "intro.md"}
        ],
    )
    rendered = render_doctor_report(report)

    assert report.ok
    assert report.probe is not None
    assert report.probe.status == "ok"
    assert "Top result" in rendered


def test_diagnose_collections_reports_zero_result_probe(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()

    report = diagnose_collections(
        {"docs": kb},
        sample_query="missing",
        sample_query_runner=lambda query, collection: [],
    )

    assert report.probe is not None
    assert report.probe.status == "zero-results"
    assert "broader query" in (report.probe.message or "")


def test_registry_probe_skips_missing_indexes(tmp_path):
    import pytest

    from trace_search.collections.collection_registry import CollectionRegistry

    kb = tmp_path / "kb"
    kb.mkdir()
    registry = CollectionRegistry({"docs": kb})

    with pytest.raises(ValueError, match="indexes are missing"):
        registry.probe_search("intro", 5, None)


def test_registry_probe_skips_incompatible_indexes(tmp_path):
    import pytest

    from trace_search.collections.collection_registry import CollectionRegistry

    kb = tmp_path / "kb"
    kb.mkdir()
    registry = CollectionRegistry({"docs": kb})
    col = registry.collections["docs"]
    metadata = build_index_metadata(
        kb_path=kb,
        build_started_at=utc_now_iso(),
        build_completed_at=utc_now_iso(),
        document_count=0,
        chunk_count=0,
    )
    mismatched = metadata.__class__(
        **{
            **metadata.to_dict(),
            "embedding_model": "some-other-model",
        }
    )
    _publish_metadata(col.index_path, mismatched)

    with pytest.raises(ValueError, match="indexes are incompatible"):
        registry.probe_search("intro", 5, "docs")


def test_registry_probe_uses_existing_indexes_without_rebuild(tmp_path):
    from tests.test_runtime_hardening import FakeBackend
    from trace_search.collections.collection_registry import CollectionRegistry
    from trace_search.indexing.wiki_indexer import WikiIndexer

    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "intro.md").write_text("# Intro\n\nintro widget notes", encoding="utf-8")
    (kb / "other.md").write_text("# Other\n\nunrelated text", encoding="utf-8")
    registry = CollectionRegistry({"docs": kb})
    registry._backend = FakeBackend()
    registry._warmed = True
    col = registry.collections["docs"]
    WikiIndexer(kb, index_root=col.index_path, backend=FakeBackend()).build_index()
    generation = read_current(col.index_path)
    # A stale corpus must not make the probe reindex.
    (kb / "later.md").write_text("# Later\n\nlater notes", encoding="utf-8")

    hits = registry.probe_search("intro widget", 5, "docs")

    assert hits[0]["path"] == "intro.md"
    assert read_current(col.index_path) == generation
