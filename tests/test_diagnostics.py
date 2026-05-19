"""Tests for Trace doctor diagnostics."""

from trace_search.diagnostics import (
    diagnose_collections,
    diagnose_index,
    invalid_config_report,
    render_doctor_report,
    scan_corpus,
)
from trace_search.index_metadata import (
    build_index_metadata,
    utc_now_iso,
    write_index_metadata,
)
from trace_search.indexer import get_default_index_root


def _create_index_dirs(index_root):
    model_slug = "all_minilm_l6_v2"
    (index_root / f".chroma_db_{model_slug}").mkdir(parents=True)
    (index_root / f".bm25_index_{model_slug}").mkdir(parents=True)


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


def test_diagnose_index_reports_unknown_without_metadata(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    index_root = tmp_path / "indexes"
    _create_index_dirs(index_root)

    diagnosis = diagnose_index(kb, index_root)

    assert diagnosis.status == "unknown"
    assert diagnosis.last_index_time is None


def test_diagnose_index_reports_fresh_metadata(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "intro.md").write_text("# Intro", encoding="utf-8")
    index_root = get_default_index_root(kb)
    _create_index_dirs(index_root)
    completed = utc_now_iso()
    metadata = build_index_metadata(
        kb_path=kb,
        build_started_at=completed,
        build_completed_at=completed,
        document_count=1,
        chunk_count=1,
    )
    write_index_metadata(index_root, metadata)

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
    _create_index_dirs(index_root)
    completed = utc_now_iso()
    metadata = build_index_metadata(
        kb_path=kb,
        build_started_at=completed,
        build_completed_at=completed,
        document_count=3,
        chunk_count=3,
    )
    write_index_metadata(index_root, metadata)

    edit.write_text("# Edit\n\nupdated content here", encoding="utf-8")
    drop.unlink()
    (kb / "new.md").write_text("# New", encoding="utf-8")

    diagnosis = diagnose_index(kb, index_root)
    rendered = render_doctor_report(
        diagnose_collections({"docs": kb})
    )

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


def test_diagnose_index_reports_outdated_metadata_as_forced_rebuild(tmp_path):
    import json as _json

    from trace_search.index_metadata import metadata_path

    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "intro.md").write_text("# Intro", encoding="utf-8")
    index_root = get_default_index_root(kb)
    _create_index_dirs(index_root)
    metadata = build_index_metadata(
        kb_path=kb,
        build_started_at=utc_now_iso(),
        build_completed_at=utc_now_iso(),
        document_count=1,
        chunk_count=1,
    )
    write_index_metadata(index_root, metadata)
    raw = _json.loads(metadata_path(index_root).read_text(encoding="utf-8"))
    raw["version"] = 1
    metadata_path(index_root).write_text(_json.dumps(raw), encoding="utf-8")

    diagnosis = diagnose_index(kb, index_root)

    assert diagnosis.status == "unknown"
    assert diagnosis.next_reindex == "forced"
    assert diagnosis.metadata_version == 1
    assert any("v1" in msg for msg in diagnosis.messages)


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

    from trace_search.server_app import CollectionRegistry

    kb = tmp_path / "kb"
    kb.mkdir()
    registry = CollectionRegistry({"docs": kb})

    with pytest.raises(ValueError, match="indexes are missing"):
        registry.probe_search("intro", 5, None)
