"""Guarantees of the generation index store: one writer, atomic swaps, hot reload."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from tests.test_runtime_hardening import FakeBackend
from trace_search.config import settings
from trace_search.indexing.index_store import (
    ChunkMetadata,
    IndexBusyError,
    IndexSnapshot,
    read_current,
    writer_lock,
)
from trace_search.indexing.wiki_indexer import WikiIndexer
from trace_search.retrieval.search import KeywordSearch, SemanticSearch, parse_filters


@pytest.fixture
def kb(tmp_path: Path) -> Path:
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "intro.md").write_text("# Intro\n\nwelcome to the notes", encoding="utf-8")
    (kb / "notes.md").write_text("# Notes\n\nplain meeting notes", encoding="utf-8")
    (kb / "other.md").write_text("# Other\n\nunrelated text", encoding="utf-8")
    return kb


def _indexer(kb: Path, index_root: Path) -> WikiIndexer:
    return WikiIndexer(kb, index_root=index_root, backend=FakeBackend())


def _paths(hits: list[dict]) -> list[str]:
    return [hit["path"] for hit in hits]


def _generation_dirs(index_root: Path) -> set[str]:
    return {p.name for p in index_root.iterdir() if p.name.startswith("gen-")}


def test_second_writer_is_refused_while_lock_is_held(kb, tmp_path):
    index_root = tmp_path / "idx"

    with writer_lock(index_root):
        with pytest.raises(IndexBusyError, match=f"pid {os.getpid()}"):
            _indexer(kb, index_root).build_index()

    assert read_current(index_root) is None
    assert _indexer(kb, index_root).build_index() == 3


def test_reader_picks_up_another_indexers_rebuild_without_restart(kb, tmp_path):
    index_root = tmp_path / "idx"
    _indexer(kb, index_root).build_index()
    reader = _indexer(kb, index_root)
    search = KeywordSearch(reader)
    before = reader.snapshot().generation
    assert search.search("quokka") == []

    (kb / "notes.md").write_text("# Quokka notes\n\nquokka habitat", encoding="utf-8")
    _indexer(kb, index_root).build_index()

    assert reader.snapshot().generation == read_current(index_root) != before
    assert _paths(search.search("quokka")) == ["notes.md"]


def test_failed_build_keeps_previous_generation_serving(kb, tmp_path, monkeypatch):
    index_root = tmp_path / "idx"
    backend = FakeBackend()
    writer = WikiIndexer(kb, index_root=index_root, backend=backend)
    writer.build_index()
    generation = read_current(index_root)

    (kb / "notes.md").write_text("# Quokka notes\n\nquokka habitat", encoding="utf-8")

    def fail(texts: list[str]):
        raise RuntimeError("embedding model crashed")

    monkeypatch.setattr(backend, "encode", fail)
    with pytest.raises(RuntimeError, match="embedding model crashed"):
        writer.build_index()

    assert read_current(index_root) == generation
    assert _generation_dirs(index_root) == {generation}
    reader = _indexer(kb, index_root)
    assert _paths(KeywordSearch(reader).search("welcome intro")) == ["intro.md"]
    assert KeywordSearch(reader).search("quokka") == []

    # The failed build released the writer lock.
    monkeypatch.undo()
    writer.build_index()
    assert read_current(index_root) != generation


def test_publish_prunes_all_but_current_and_previous_generation(kb, tmp_path):
    index_root = tmp_path / "idx"
    indexer = _indexer(kb, index_root)
    generations = []
    for _ in range(3):
        indexer.build_index(force=True)
        generations.append(read_current(index_root))
    leftover = index_root / "gen-19700101T000000-000000000.tmp"
    leftover.mkdir()
    (leftover / "chunks.json").write_text("{", encoding="utf-8")

    indexer.build_index(force=True)
    generations.append(read_current(index_root))

    assert len(set(generations)) == 4
    assert _generation_dirs(index_root) == set(generations[-2:])


def test_snapshot_rejects_inconsistent_row_counts():
    chunk: ChunkMetadata = {
        "path": "a.md",
        "title": "A",
        "folder": "",
        "chunk_index": 0,
        "chunk_count": 1,
        "breadcrumb": "A",
        "extension": ".md",
        "source_mtime": 0.0,
    }
    good = {
        "chunk_ids": ["a.md::0"],
        "texts": ["alpha"],
        "chunks": [chunk],
        "embeddings": np.ones((1, 3), dtype=np.float32),
    }
    bad_rows = [
        {"chunk_ids": ["a.md::0", "b.md::0"]},
        {"texts": []},
        {"embeddings": np.ones((2, 3), dtype=np.float32)},
    ]

    for override in bad_rows:
        with pytest.raises(ValueError, match="inconsistent"):
            IndexSnapshot.build(**{**good, **override}, k1=1.2, b=0.5)


class _QueryBackend:
    """Embeds every query onto the first axis, which the outside chunks match."""

    model_name = "fake"
    dim = 3

    def encode_one(self, text: str):
        return np.asarray([1.0, 0.0, 0.0], dtype=np.float32)


def _prefix_snapshot_indexer() -> SimpleNamespace:
    # Enough out-of-prefix chunks outrank the one in-prefix chunk to fill every
    # candidate pool, so a filter applied after ranking would return nothing.
    outside = 600
    paths = [f"raw/dump-{i}.md" for i in range(outside)] + ["wiki/router.md"]
    texts = ["router router router"] * outside + ["router guide and setup notes"]
    chunks: list[ChunkMetadata] = [
        {
            "path": path,
            "title": path,
            "folder": path.split("/")[0],
            "chunk_index": 0,
            "chunk_count": 1,
            "breadcrumb": path,
            "extension": ".md",
            "source_mtime": 0.0,
        }
        for path in paths
    ]
    embeddings = np.asarray(
        [[1.0, 0.0, 0.0]] * outside + [[0.6, 0.8, 0.0]], dtype=np.float32
    )
    snapshot = IndexSnapshot.build(
        chunk_ids=[f"{path}::0" for path in paths],
        texts=texts,
        chunks=chunks,
        embeddings=embeddings,
        k1=settings.bm25_k1,
        b=settings.bm25_b,
    )
    return SimpleNamespace(snapshot=lambda: snapshot, backend=_QueryBackend())


def test_path_prefix_filter_ranks_only_matching_rows():
    indexer = _prefix_snapshot_indexer()
    wiki = parse_filters(path_prefix="wiki/")
    SemanticSearch._embedding_cache.clear()

    keyword_hits = KeywordSearch(indexer).search("router", 5, filters=wiki)
    semantic_hits = SemanticSearch(indexer).search("router", 5, filters=wiki)

    assert _paths(keyword_hits) == ["wiki/router.md"]
    assert _paths(semantic_hits) == ["wiki/router.md"]
    SemanticSearch._embedding_cache.clear()
