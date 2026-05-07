"""Tests for versioned index metadata helpers."""

import os

from trace_search.index_metadata import (
    build_index_metadata,
    collect_source_files,
    metadata_matches_active_model,
    read_index_metadata,
    stale_source_paths,
    utc_now_iso,
    write_index_metadata,
)


def test_metadata_round_trip_records_active_model_and_sources(tmp_path):
    kb = tmp_path / "kb"
    index_root = tmp_path / "indexes"
    kb.mkdir()
    (kb / "intro.md").write_text("# Intro\n\nBM25 notes", encoding="utf-8")

    metadata = build_index_metadata(
        kb_path=kb,
        build_started_at=utc_now_iso(),
        build_completed_at=utc_now_iso(),
        document_count=1,
        chunk_count=2,
    )
    write_index_metadata(index_root, metadata)

    loaded = read_index_metadata(index_root)

    assert loaded is not None
    assert loaded.version == 1
    assert loaded.document_count == 1
    assert loaded.chunk_count == 2
    assert loaded.source_files[0].path == "intro.md"
    assert metadata_matches_active_model(loaded)


def test_missing_metadata_returns_none(tmp_path):
    assert read_index_metadata(tmp_path / "missing") is None


def test_model_mismatch_detection(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
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
            "embedding_model": "different-model",
        }
    )

    assert not metadata_matches_active_model(mismatched)


def test_stale_source_paths_detects_changed_files(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    doc = kb / "intro.md"
    doc.write_text("# Intro\n\nOld", encoding="utf-8")
    metadata = build_index_metadata(
        kb_path=kb,
        build_started_at=utc_now_iso(),
        build_completed_at=utc_now_iso(),
        document_count=1,
        chunk_count=1,
    )

    doc.write_text("# Intro\n\nNew and longer", encoding="utf-8")
    os.utime(doc, None)

    assert stale_source_paths(kb, metadata) == ["intro.md"]


def test_collect_source_files_skips_outside_symlink(tmp_path):
    kb = tmp_path / "kb"
    outside = tmp_path / "outside"
    kb.mkdir()
    outside.mkdir()
    (kb / "intro.md").write_text("# Intro", encoding="utf-8")
    target = outside / "secret.md"
    target.write_text("# Secret", encoding="utf-8")
    (kb / "secret-link.md").symlink_to(target)

    records = collect_source_files(kb)

    assert [record.path for record in records] == ["intro.md"]
