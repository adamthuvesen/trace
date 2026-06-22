"""Tests for versioned index metadata helpers."""

import json
import os

from trace_search.indexing.index_metadata import (
    INDEX_METADATA_VERSION,
    SourceFileRecord,
    build_index_metadata,
    categorize_source_changes,
    collect_source_files,
    hash_file,
    invalidate_index_metadata,
    metadata_matches_active_model,
    metadata_path,
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
    assert loaded.version == INDEX_METADATA_VERSION
    assert loaded.document_count == 1
    assert loaded.chunk_count == 2
    record = loaded.source_files[0]
    assert record.path == "intro.md"
    assert record.content_sha
    assert metadata_matches_active_model(loaded)


def test_missing_metadata_returns_none(tmp_path):
    assert read_index_metadata(tmp_path / "missing") is None


def test_older_metadata_version_is_treated_as_missing(tmp_path):
    kb = tmp_path / "kb"
    index_root = tmp_path / "indexes"
    kb.mkdir()
    (kb / "intro.md").write_text("# Intro", encoding="utf-8")
    metadata = build_index_metadata(
        kb_path=kb,
        build_started_at=utc_now_iso(),
        build_completed_at=utc_now_iso(),
        document_count=1,
        chunk_count=1,
    )
    write_index_metadata(index_root, metadata)

    raw = json.loads(metadata_path(index_root).read_text(encoding="utf-8"))
    raw["version"] = 1
    metadata_path(index_root).write_text(json.dumps(raw), encoding="utf-8")

    assert read_index_metadata(index_root) is None


def test_invalidate_index_metadata_is_idempotent(tmp_path):
    index_root = tmp_path / "indexes"
    invalidate_index_metadata(index_root)  # no metadata file yet — must not raise

    index_root.mkdir()
    metadata_path(index_root).write_text("{}", encoding="utf-8")
    invalidate_index_metadata(index_root)
    assert not metadata_path(index_root).exists()


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


def test_collect_source_files_reuses_prior_hash_when_stat_matches(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    doc = kb / "intro.md"
    doc.write_text("# Intro", encoding="utf-8")
    first = collect_source_files(kb)
    assert first[0].content_sha

    sentinel_hash = "sentinel"
    spoofed = [
        SourceFileRecord(
            path=record.path,
            extension=record.extension,
            mtime=record.mtime,
            size=record.size,
            content_sha=sentinel_hash,
        )
        for record in first
    ]

    second = collect_source_files(kb, prior=spoofed)
    assert second[0].content_sha == sentinel_hash


def test_collect_source_files_rehashes_when_size_changes(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    doc = kb / "intro.md"
    doc.write_text("short", encoding="utf-8")
    first = collect_source_files(kb)

    doc.write_text("much longer content now", encoding="utf-8")
    os.utime(doc, None)

    second = collect_source_files(kb, prior=first)
    assert second[0].content_sha != first[0].content_sha


def test_categorize_source_changes_detects_added_changed_removed(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    keep = kb / "keep.md"
    keep.write_text("# Keep", encoding="utf-8")
    edit = kb / "edit.md"
    edit.write_text("# Edit\n\nOriginal", encoding="utf-8")
    drop = kb / "drop.md"
    drop.write_text("# Drop", encoding="utf-8")

    metadata = build_index_metadata(
        kb_path=kb,
        build_started_at=utc_now_iso(),
        build_completed_at=utc_now_iso(),
        document_count=3,
        chunk_count=3,
    )

    edit.write_text("# Edit\n\nUpdated content", encoding="utf-8")
    drop.unlink()
    (kb / "new.md").write_text("# New", encoding="utf-8")

    changes = categorize_source_changes(kb, metadata)

    assert changes.unchanged == ["keep.md"]
    assert changes.added == ["new.md"]
    assert changes.changed == ["edit.md"]
    assert changes.removed == ["drop.md"]
    assert changes.has_changes is True
    assert {record.path for record in changes.inventory} == {
        "keep.md",
        "edit.md",
        "new.md",
    }


def test_categorize_source_changes_hash_match_after_touch(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    doc = kb / "intro.md"
    doc.write_text("# Intro", encoding="utf-8")
    metadata = build_index_metadata(
        kb_path=kb,
        build_started_at=utc_now_iso(),
        build_completed_at=utc_now_iso(),
        document_count=1,
        chunk_count=1,
    )

    future = doc.stat().st_mtime + 5_000
    os.utime(doc, (future, future))

    changes = categorize_source_changes(kb, metadata)

    assert changes.changed == []
    assert changes.unchanged == ["intro.md"]
    assert changes.has_changes is False


def test_categorize_source_changes_hash_mismatch_with_same_size(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    doc = kb / "intro.md"
    doc.write_text("aaaaa", encoding="utf-8")
    metadata = build_index_metadata(
        kb_path=kb,
        build_started_at=utc_now_iso(),
        build_completed_at=utc_now_iso(),
        document_count=1,
        chunk_count=1,
    )

    doc.write_text("bbbbb", encoding="utf-8")
    os.utime(doc, None)

    changes = categorize_source_changes(kb, metadata)

    assert changes.changed == ["intro.md"]
    assert changes.unchanged == []


def test_categorize_source_changes_with_no_prior_metadata(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "a.md").write_text("# A", encoding="utf-8")
    (kb / "b.md").write_text("# B", encoding="utf-8")

    changes = categorize_source_changes(kb, metadata=None)

    assert sorted(changes.added) == ["a.md", "b.md"]
    assert changes.unchanged == []
    assert changes.changed == []
    assert changes.removed == []
    assert changes.has_changes is True


def test_stale_source_paths_compat_wrapper(tmp_path):
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


def test_hash_file_is_streaming_and_stable(tmp_path):
    big = tmp_path / "blob.md"
    payload = b"# Header\n\n" + (b"line of content\n" * 50_000)
    big.write_bytes(payload)
    first = hash_file(big)
    second = hash_file(big)
    assert first == second
    assert len(first) == 64
