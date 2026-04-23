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
