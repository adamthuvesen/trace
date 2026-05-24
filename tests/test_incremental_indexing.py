"""End-to-end tests for the incremental reindex path."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.test_runtime_hardening import FakeBackend
from trace_search.config import settings
from trace_search.index_metadata import (
    INDEX_METADATA_VERSION,
    metadata_path,
    read_index_metadata,
)
from trace_search.indexer import WikiIndexer


@pytest.fixture
def kb_paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    kb = tmp_path / "kb"
    kb.mkdir()
    return kb, tmp_path / "chroma", tmp_path / "bm25"


def _make_indexer(kb: Path, chroma: Path, bm25: Path) -> WikiIndexer:
    return WikiIndexer(
        kb_path=kb,
        chroma_path=chroma,
        bm25_path=bm25,
        backend=FakeBackend(),
    )


def _chunk_paths(indexer: WikiIndexer) -> list[str]:
    result = indexer.collection.get(include=["metadatas"])
    return sorted(meta["path"] for meta in (result.get("metadatas") or []))


def test_initial_build_writes_v2_metadata_with_hashes(kb_paths):
    kb, chroma, bm25 = kb_paths
    (kb / "intro.md").write_text("# Intro\n\nhello world", encoding="utf-8")
    (kb / "notes.md").write_text("# Notes\n\nmore content", encoding="utf-8")

    indexer = _make_indexer(kb, chroma, bm25)
    chunks = indexer.build_index(force=True)

    assert chunks == 2
    meta = read_index_metadata(bm25.parent)
    assert meta is not None
    assert meta.version == INDEX_METADATA_VERSION
    assert {record.path for record in meta.source_files} == {"intro.md", "notes.md"}
    assert all(record.content_sha for record in meta.source_files)


def test_incremental_rebuild_skips_unchanged_files(kb_paths):
    kb, chroma, bm25 = kb_paths
    (kb / "keep.md").write_text("# Keep\n\nstable content", encoding="utf-8")
    (kb / "edit.md").write_text("# Edit\n\noriginal", encoding="utf-8")

    indexer = _make_indexer(kb, chroma, bm25)
    indexer.build_index(force=True)
    before = indexer.collection.get(include=["documents", "metadatas"])
    before_by_path = {
        meta["path"]: doc for meta, doc in zip(before["metadatas"], before["documents"])
    }

    (kb / "edit.md").write_text("# Edit\n\nupdated content", encoding="utf-8")
    os.utime(kb / "edit.md", None)

    fresh = _make_indexer(kb, chroma, bm25)
    fresh.build_index()

    after = fresh.collection.get(include=["documents", "metadatas"])
    after_by_path = {
        meta["path"]: doc for meta, doc in zip(after["metadatas"], after["documents"])
    }
    assert after_by_path["keep.md"] == before_by_path["keep.md"]
    assert after_by_path["edit.md"] != before_by_path["edit.md"]
    assert "updated content" in after_by_path["edit.md"]


def test_incremental_rebuild_removes_deleted_files(kb_paths):
    kb, chroma, bm25 = kb_paths
    (kb / "keep.md").write_text("# Keep", encoding="utf-8")
    (kb / "drop.md").write_text("# Drop", encoding="utf-8")

    indexer = _make_indexer(kb, chroma, bm25)
    indexer.build_index(force=True)
    assert _chunk_paths(indexer) == ["drop.md", "keep.md"]

    (kb / "drop.md").unlink()

    fresh = _make_indexer(kb, chroma, bm25)
    fresh.build_index()

    assert _chunk_paths(fresh) == ["keep.md"]


def test_incremental_rebuild_adds_new_files(kb_paths):
    kb, chroma, bm25 = kb_paths
    (kb / "intro.md").write_text("# Intro", encoding="utf-8")

    indexer = _make_indexer(kb, chroma, bm25)
    indexer.build_index(force=True)

    (kb / "fresh.md").write_text("# Fresh\n\nnew content", encoding="utf-8")

    fresh = _make_indexer(kb, chroma, bm25)
    fresh.build_index()

    assert _chunk_paths(fresh) == ["fresh.md", "intro.md"]


def test_no_changes_keeps_index_untouched(kb_paths):
    kb, chroma, bm25 = kb_paths
    (kb / "intro.md").write_text("# Intro", encoding="utf-8")

    indexer = _make_indexer(kb, chroma, bm25)
    indexer.build_index(force=True)
    meta_before = metadata_path(bm25.parent).read_text(encoding="utf-8")
    bm25_file = next(bm25.rglob("*"), None)
    bm25_mtime = bm25_file.stat().st_mtime if bm25_file else None

    fresh = _make_indexer(kb, chroma, bm25)
    fresh.build_index()

    assert metadata_path(bm25.parent).read_text(encoding="utf-8") == meta_before
    if bm25_file is not None:
        assert bm25_file.stat().st_mtime == bm25_mtime


def test_force_flag_drops_and_rebuilds_everything(kb_paths):
    kb, chroma, bm25 = kb_paths
    (kb / "intro.md").write_text("# Intro", encoding="utf-8")

    indexer = _make_indexer(kb, chroma, bm25)
    indexer.build_index(force=True)
    first_ids = sorted(indexer.collection.get()["ids"])

    indexer2 = _make_indexer(kb, chroma, bm25)
    indexer2.build_index(force=True)
    second_ids = sorted(indexer2.collection.get()["ids"])

    assert first_ids == second_ids


def test_outdated_metadata_promotes_to_full_rebuild(kb_paths):
    kb, chroma, bm25 = kb_paths
    (kb / "intro.md").write_text("# Intro", encoding="utf-8")

    indexer = _make_indexer(kb, chroma, bm25)
    indexer.build_index(force=True)

    raw = metadata_path(bm25.parent).read_text(encoding="utf-8")
    metadata_path(bm25.parent).write_text(
        raw.replace(f'"version": {INDEX_METADATA_VERSION}', '"version": 1'),
        encoding="utf-8",
    )

    fresh = _make_indexer(kb, chroma, bm25)
    fresh.build_index()  # no force; should still rebuild

    meta = read_index_metadata(bm25.parent)
    assert meta is not None
    assert meta.version == INDEX_METADATA_VERSION


def test_embedding_backend_mismatch_promotes_to_full_rebuild(kb_paths):
    kb, chroma, bm25 = kb_paths
    (kb / "intro.md").write_text("# Intro", encoding="utf-8")

    indexer = _make_indexer(kb, chroma, bm25)
    indexer.build_index(force=True)

    raw = json.loads(metadata_path(bm25.parent).read_text(encoding="utf-8"))
    stale_backend = "torch" if settings.embedding_backend != "torch" else "onnx"
    raw["embedding_backend"] = stale_backend
    metadata_path(bm25.parent).write_text(json.dumps(raw), encoding="utf-8")

    fresh = _make_indexer(kb, chroma, bm25)
    fresh.build_index()

    meta = read_index_metadata(bm25.parent)
    assert meta is not None
    assert meta.embedding_backend != stale_backend


def test_chunk_ids_are_stable_for_unchanged_files(kb_paths):
    kb, chroma, bm25 = kb_paths
    (kb / "intro.md").write_text(
        "# Intro\n\nfirst paragraph\n\n## Section\n\nsecond paragraph",
        encoding="utf-8",
    )

    indexer = _make_indexer(kb, chroma, bm25)
    indexer.build_index(force=True)
    first_ids = sorted(indexer.collection.get()["ids"])

    indexer2 = _make_indexer(kb, chroma, bm25)
    indexer2.build_index(force=True)
    second_ids = sorted(indexer2.collection.get()["ids"])

    assert first_ids == second_ids
    assert all(cid.startswith("intro.md::") for cid in first_ids)


def test_chunk_metadata_carries_extension_and_source_mtime(kb_paths):
    kb, chroma, bm25 = kb_paths
    doc = kb / "intro.md"
    doc.write_text("# Intro\n\nhello", encoding="utf-8")

    indexer = _make_indexer(kb, chroma, bm25)
    indexer.build_index(force=True)

    metas = indexer.collection.get(include=["metadatas"])["metadatas"]
    assert all(meta.get("extension") == ".md" for meta in metas)
    assert all(float(meta.get("source_mtime") or 0) > 0 for meta in metas)


def test_incremental_failure_invalidates_metadata(kb_paths, monkeypatch):
    kb, chroma, bm25 = kb_paths
    (kb / "intro.md").write_text("# Intro", encoding="utf-8")

    indexer = _make_indexer(kb, chroma, bm25)
    indexer.build_index(force=True)
    (kb / "intro.md").write_text("# Intro\n\nedited", encoding="utf-8")
    os.utime(kb / "intro.md", None)

    fresh = _make_indexer(kb, chroma, bm25)

    def boom(self, changes):  # noqa: ARG001
        raise RuntimeError("simulated incremental failure")

    monkeypatch.setattr(WikiIndexer, "_apply_incremental_changes", boom)

    with pytest.raises(RuntimeError, match="simulated incremental failure"):
        fresh.build_index()

    assert not metadata_path(bm25.parent).exists()
