"""End-to-end tests for the incremental reindex path."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.test_runtime_hardening import FakeBackend
from trace_search.config import settings
from trace_search.indexing.index_metadata import INDEX_METADATA_VERSION
from trace_search.indexing.index_store import read_current, read_current_metadata
from trace_search.indexing.wiki_indexer import WikiIndexer
from trace_search.retrieval.search import KeywordSearch


@pytest.fixture
def kb_paths(tmp_path: Path) -> tuple[Path, Path]:
    kb = tmp_path / "kb"
    kb.mkdir()
    return kb, tmp_path / "indexes"


def _make_indexer(kb: Path, index_root: Path) -> WikiIndexer:
    return WikiIndexer(kb_path=kb, index_root=index_root, backend=FakeBackend())


def _chunk_paths(indexer: WikiIndexer) -> list[str]:
    return sorted(chunk["path"] for chunk in indexer.snapshot().chunks)


def _texts_by_path(indexer: WikiIndexer) -> dict[str, str]:
    snapshot = indexer.snapshot()
    return {chunk["path"]: text for chunk, text in zip(snapshot.chunks, snapshot.texts)}


def _current_metadata_file(index_root: Path) -> Path:
    generation = read_current(index_root)
    assert generation is not None
    return index_root / generation / "index_metadata.json"


def test_initial_build_writes_current_metadata_with_hashes(kb_paths):
    kb, index_root = kb_paths
    (kb / "intro.md").write_text("# Intro\n\nhello world", encoding="utf-8")
    (kb / "notes.md").write_text("# Notes\n\nmore content", encoding="utf-8")

    indexer = _make_indexer(kb, index_root)
    chunks = indexer.build_index(force=True)

    assert chunks == 2
    meta = read_current_metadata(index_root)
    assert meta is not None
    assert meta.version == INDEX_METADATA_VERSION
    assert {record.path for record in meta.source_files} == {"intro.md", "notes.md"}
    assert all(record.content_sha for record in meta.source_files)


def test_full_rebuild_keeps_bm25_content_available_in_memory(kb_paths):
    kb, index_root = kb_paths
    (kb / "bm25.md").write_text(
        "# BM25\n\nBM25 is a keyword ranking function.",
        encoding="utf-8",
    )
    indexer = _make_indexer(kb, index_root)

    indexer.build_index(force=True)
    hits = KeywordSearch(indexer).search("BM25", max_results=1)

    assert hits
    assert "keyword ranking" in hits[0]["content"]


def test_incremental_rebuild_skips_unchanged_files(kb_paths):
    kb, index_root = kb_paths
    (kb / "keep.md").write_text("# Keep\n\nstable content", encoding="utf-8")
    (kb / "edit.md").write_text("# Edit\n\noriginal", encoding="utf-8")

    indexer = _make_indexer(kb, index_root)
    indexer.build_index(force=True)
    before_by_path = _texts_by_path(indexer)

    (kb / "edit.md").write_text("# Edit\n\nupdated content", encoding="utf-8")
    os.utime(kb / "edit.md", None)

    fresh = _make_indexer(kb, index_root)
    fresh.build_index()

    after_by_path = _texts_by_path(fresh)
    assert after_by_path["keep.md"] == before_by_path["keep.md"]
    assert after_by_path["edit.md"] != before_by_path["edit.md"]
    assert "updated content" in after_by_path["edit.md"]


def test_incremental_rebuild_removes_deleted_files(kb_paths):
    kb, index_root = kb_paths
    (kb / "keep.md").write_text("# Keep", encoding="utf-8")
    (kb / "drop.md").write_text("# Drop", encoding="utf-8")

    indexer = _make_indexer(kb, index_root)
    indexer.build_index(force=True)
    assert _chunk_paths(indexer) == ["drop.md", "keep.md"]

    (kb / "drop.md").unlink()

    fresh = _make_indexer(kb, index_root)
    fresh.build_index()

    assert _chunk_paths(fresh) == ["keep.md"]


def test_incremental_rebuild_removes_newly_traceignored_files(kb_paths):
    kb, index_root = kb_paths
    (kb / "wiki").mkdir()
    (kb / "wiki" / "keep.md").write_text("# Keep", encoding="utf-8")
    (kb / "raw.md").write_text("# Raw", encoding="utf-8")

    indexer = _make_indexer(kb, index_root)
    indexer.build_index(force=True)
    assert _chunk_paths(indexer) == ["raw.md", "wiki/keep.md"]

    (kb / ".traceignore").write_text("/*\n!/wiki/\n", encoding="utf-8")

    fresh = _make_indexer(kb, index_root)
    fresh.build_index()

    assert _chunk_paths(fresh) == ["wiki/keep.md"]
    meta = read_current_metadata(index_root)
    assert meta is not None
    assert [record.path for record in meta.source_files] == ["wiki/keep.md"]


def test_incremental_rebuild_adds_new_files(kb_paths):
    kb, index_root = kb_paths
    (kb / "intro.md").write_text("# Intro", encoding="utf-8")

    indexer = _make_indexer(kb, index_root)
    indexer.build_index(force=True)

    (kb / "fresh.md").write_text("# Fresh\n\nnew content", encoding="utf-8")

    fresh = _make_indexer(kb, index_root)
    fresh.build_index()

    assert _chunk_paths(fresh) == ["fresh.md", "intro.md"]


def test_no_changes_keeps_index_untouched(kb_paths):
    kb, index_root = kb_paths
    (kb / "intro.md").write_text("# Intro", encoding="utf-8")

    indexer = _make_indexer(kb, index_root)
    indexer.build_index(force=True)
    generation_before = read_current(index_root)

    fresh = _make_indexer(kb, index_root)
    fresh.build_index()

    assert read_current(index_root) == generation_before


def test_force_flag_drops_and_rebuilds_everything(kb_paths):
    kb, index_root = kb_paths
    (kb / "intro.md").write_text("# Intro", encoding="utf-8")

    indexer = _make_indexer(kb, index_root)
    indexer.build_index(force=True)
    first_ids = sorted(indexer.snapshot().chunk_ids)

    indexer2 = _make_indexer(kb, index_root)
    indexer2.build_index(force=True)
    second_ids = sorted(indexer2.snapshot().chunk_ids)

    assert first_ids == second_ids


def test_outdated_metadata_promotes_to_full_rebuild(kb_paths):
    kb, index_root = kb_paths
    (kb / "intro.md").write_text("# Intro", encoding="utf-8")

    indexer = _make_indexer(kb, index_root)
    indexer.build_index(force=True)

    metadata_file = _current_metadata_file(index_root)
    raw = metadata_file.read_text(encoding="utf-8")
    metadata_file.write_text(
        raw.replace(f'"version": {INDEX_METADATA_VERSION}', '"version": 1'),
        encoding="utf-8",
    )

    fresh = _make_indexer(kb, index_root)
    fresh.build_index()  # no force; should still rebuild

    meta = read_current_metadata(index_root)
    assert meta is not None
    assert meta.version == INDEX_METADATA_VERSION


def test_embedding_model_mismatch_promotes_to_full_rebuild(kb_paths):
    kb, index_root = kb_paths
    (kb / "intro.md").write_text("# Intro", encoding="utf-8")

    indexer = _make_indexer(kb, index_root)
    indexer.build_index(force=True)

    metadata_file = _current_metadata_file(index_root)
    raw = json.loads(metadata_file.read_text(encoding="utf-8"))
    raw["embedding_model"] = "some-other-model"
    metadata_file.write_text(json.dumps(raw), encoding="utf-8")

    fresh = _make_indexer(kb, index_root)
    fresh.build_index()

    meta = read_current_metadata(index_root)
    assert meta is not None
    assert meta.embedding_model == settings.embedding_model


def test_chunk_ids_are_stable_for_unchanged_files(kb_paths):
    kb, index_root = kb_paths
    (kb / "intro.md").write_text(
        "# Intro\n\nfirst paragraph\n\n## Section\n\nsecond paragraph",
        encoding="utf-8",
    )

    indexer = _make_indexer(kb, index_root)
    indexer.build_index(force=True)
    first_ids = sorted(indexer.snapshot().chunk_ids)

    indexer2 = _make_indexer(kb, index_root)
    indexer2.build_index(force=True)
    second_ids = sorted(indexer2.snapshot().chunk_ids)

    assert first_ids == second_ids
    assert all(cid.startswith("intro.md::") for cid in first_ids)


def test_chunk_metadata_carries_extension_and_source_mtime(kb_paths):
    kb, index_root = kb_paths
    doc = kb / "intro.md"
    doc.write_text("# Intro\n\nhello", encoding="utf-8")

    indexer = _make_indexer(kb, index_root)
    indexer.build_index(force=True)

    chunks = indexer.snapshot().chunks
    assert chunks
    assert all(chunk["extension"] == ".md" for chunk in chunks)
    assert all(chunk["source_mtime"] > 0 for chunk in chunks)
